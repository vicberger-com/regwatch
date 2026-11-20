"""Groups of users (ADR-0012, CP-27, M11.4).

A group's roles apply to its members, so adding a member or a role to a group is granting
permissions, and every rule for granting them to a user holds here too: changes run one at a
time with user and role changes, an administrator grants only what they hold, and each change
is audited. No group carries ``users.manage`` or ``roles.manage``: those stay with each user,
so the last-manager guard is unchanged.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.errors import ProblemError
from regwatch.core.services import audit
from regwatch.identity.models import GroupMember, GroupRole, Role, User, UserGroup
from regwatch.identity.schemas import Group as GroupOut
from regwatch.identity.services import (
    GROUP_FORBIDDEN,
    Principal,
    _perms_of_roles,
    _require_held,
    _serialise_admin_changes,
    validation,
)

MAX_GROUPS = 200


async def _roles_of(db: AsyncSession, group_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    out: dict[uuid.UUID, list[str]] = {g: [] for g in group_ids}
    query = (select(GroupRole.group_id, Role.key).join(Role, Role.id == GroupRole.role_id)
             .where(GroupRole.group_id.in_(group_ids)).order_by(Role.key))  # fmt: skip
    rows = await db.execute(query)
    for gid, key in rows.tuples().all():
        out[gid].append(key)
    return out


async def _members_of(
    db: AsyncSession, group_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    out: dict[uuid.UUID, list[uuid.UUID]] = {g: [] for g in group_ids}
    rows = await db.execute(select(GroupMember.group_id, GroupMember.user_id)
                            .where(GroupMember.group_id.in_(group_ids))
                            .order_by(GroupMember.user_id))  # fmt: skip
    for gid, uid in rows.tuples().all():
        out[gid].append(uid)
    return out


async def _out(db: AsyncSession, group: UserGroup) -> GroupOut:
    roles = (await _roles_of(db, [group.id]))[group.id]
    members = (await _members_of(db, [group.id]))[group.id]
    return GroupOut(id=group.id, key=group.key, name=group.name, description=group.description,
                    roles=roles, members=members)  # fmt: skip


async def list_groups(db: AsyncSession) -> list[GroupOut]:
    groups = (await db.scalars(select(UserGroup).order_by(UserGroup.name, UserGroup.id)
                               .limit(MAX_GROUPS))).all()  # fmt: skip
    ids = [g.id for g in groups]
    roles, members = await _roles_of(db, ids), await _members_of(db, ids)
    return [GroupOut(id=g.id, key=g.key, name=g.name, description=g.description,
                     roles=roles[g.id], members=members[g.id]) for g in groups]  # fmt: skip


async def _group_or_404(db: AsyncSession, group_id: uuid.UUID) -> UserGroup:
    group = await db.scalar(select(UserGroup).where(UserGroup.id == group_id).with_for_update())
    if group is None:
        raise ProblemError(404, "not-found", "No such group.")
    return group


async def _role_ids(db: AsyncSession, keys: list[str], actor: Principal) -> list[uuid.UUID]:
    """The roles a group may carry: known, without admin-tier permissions, and held by the
    actor (who grants them to every member)."""
    wanted = sorted(set(keys))
    found = dict((await db.execute(select(Role.key, Role.id).where(Role.key.in_(wanted)))
                  ).tuples().all())  # fmt: skip
    if missing := [k for k in wanted if k not in found]:
        raise validation("roles", f"unknown roles: {', '.join(missing)}")
    perms = await _perms_of_roles(db, wanted)
    if banned := sorted(perms & GROUP_FORBIDDEN):
        raise validation("roles", f"A group cannot hold {', '.join(banned)}; grant it to "
                         "each user directly.")  # fmt: skip
    _require_held(actor, perms, "grant")
    return [found[k] for k in wanted]


def _text(changes: dict[str, Any], key: str) -> str | None:
    value = changes.get(key)
    return value.strip() or None if isinstance(value, str) else None


async def create_group(db: AsyncSession, changes: dict[str, Any], actor: Principal,
                       ip: str | None) -> GroupOut:  # fmt: skip
    await _serialise_admin_changes(db)
    name = _text(changes, "name")
    if not changes.get("key") or not name:
        raise validation(
            "key" if not changes.get("key") else "name", "a key and a name are required"
        )
    if await db.scalar(select(UserGroup.id).where(UserGroup.key == changes["key"])):
        raise ProblemError(409, "conflict", "A group with this key exists.")
    role_ids = await _role_ids(db, changes.get("roles") or [], actor)
    group = UserGroup(key=changes["key"], name=name, description=_text(changes, "description"))
    db.add(group)
    await db.flush()
    db.add_all(GroupRole(group_id=group.id, role_id=r) for r in role_ids)
    await db.flush()
    out = await _out(db, group)
    audit(db, "group.create", "user_group", group.id, actor=actor.user.id, ip=ip,
          after=out.model_dump(mode="json", exclude={"id", "members"}))  # fmt: skip
    await db.commit()
    return out


async def update_group(db: AsyncSession, group_id: uuid.UUID, changes: dict[str, Any],
                       actor: Principal, ip: str | None) -> GroupOut:  # fmt: skip
    await _serialise_admin_changes(db)
    group = await _group_or_404(db, group_id)
    before = (await _out(db, group)).model_dump(mode="json", exclude={"id", "members"})
    if "key" in changes and changes["key"] != group.key:
        if await db.scalar(select(UserGroup.id).where(UserGroup.key == changes["key"])):
            raise ProblemError(409, "conflict", "A group with this key exists.")
        group.key = changes["key"]
    if "name" in changes:
        if not (name := _text(changes, "name")):
            raise validation("name", "a name is required")
        group.name = name
    if "description" in changes:
        group.description = _text(changes, "description")
    if "roles" in changes:
        role_ids = await _role_ids(db, changes["roles"] or [], actor)
        # Taking a role away from members also needs it held (as for a user's roles).
        _require_held(actor, await _perms_of_roles(db, before["roles"]), "manage holders of")
        await db.execute(delete(GroupRole).where(GroupRole.group_id == group.id))
        db.add_all(GroupRole(group_id=group.id, role_id=r) for r in role_ids)
    await db.flush()
    out = await _out(db, group)
    after = out.model_dump(mode="json", exclude={"id", "members"})
    if after != before:
        audit(db, "group.update", "user_group", group.id, actor=actor.user.id, ip=ip,
              before=before, after=after)  # fmt: skip
    await db.commit()
    return out


async def delete_group(db: AsyncSession, group_id: uuid.UUID, actor: Principal,
                       ip: str | None) -> None:  # fmt: skip
    await _serialise_admin_changes(db)
    group = await _group_or_404(db, group_id)
    out = await _out(db, group)
    _require_held(actor, await _perms_of_roles(db, out.roles), "manage holders of")
    audit(db, "group.delete", "user_group", group.id, actor=actor.user.id, ip=ip,
          before=out.model_dump(mode="json", exclude={"id"}))  # fmt: skip
    await db.delete(group)
    await db.commit()


async def set_member(db: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID, member: bool,
                     actor: Principal, ip: str | None) -> None:  # fmt: skip
    """Add or remove a member: the actor must hold the group's permissions either way."""
    await _serialise_admin_changes(db)
    group = await _group_or_404(db, group_id)
    if await db.get(User, user_id) is None:
        raise ProblemError(404, "not-found", "No such user.")
    roles = (await _roles_of(db, [group.id]))[group.id]
    _require_held(
        actor, await _perms_of_roles(db, roles), "grant" if member else "manage holders of"
    )
    where = (GroupMember.group_id == group.id, GroupMember.user_id == user_id)
    present = await db.scalar(select(GroupMember.user_id).where(*where)) is not None
    if present == member:
        await db.rollback()
        return
    if member:
        await db.execute(insert(GroupMember).values(group_id=group.id, user_id=user_id)
                         .on_conflict_do_nothing())  # fmt: skip
    else:
        await db.execute(delete(GroupMember).where(*where))
    audit(db, "group.member_add" if member else "group.member_remove", "user_group", group.id,
          actor=actor.user.id, ip=ip, after={"user_id": str(user_id), "roles": roles})  # fmt: skip
    await db.commit()
