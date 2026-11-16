import { useEffect, useRef, useState, type FormEvent } from "react";

import { problemText } from "@/lib/auth/session";

import { useUpdateUser, type User } from "./api";

const field = "rounded border border-border bg-bg px-2 py-1";
const button = "rounded border border-border px-2 py-1 disabled:opacity-50";

/**
 * Edit an existing user's name and roles (screens.md "create and edit dialog"; use testing
 * U-M1-2). Focus moves to the form's heading when it opens, and Escape closes it (U-M0-3).
 * One's own roles are not edited here, so nobody removes their own access by accident.
 */
export function UserEditor(props: {
  user: User;
  roleKeys: string[];
  isSelf: boolean;
  onClose: () => void;
  onSaved: (user: User) => void;
}) {
  const { user, roleKeys, isSelf } = props;
  const update = useUpdateUser();
  const [name, setName] = useState(user.display_name);
  const [roles, setRoles] = useState<string[]>(user.roles);
  const heading = useRef<HTMLHeadingElement>(null);

  const onClose = useRef(props.onClose);
  useEffect(() => {
    onClose.current = props.onClose;
  });
  useEffect(() => {
    heading.current?.focus(); // once, when the form opens
    const close = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose.current();
    };
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("keydown", close);
    };
  }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    const body = isSelf
      ? { display_name: name }
      : { display_name: name, roles };
    update.mutate({ id: user.id, body }, { onSuccess: props.onSaved });
  }

  return (
    <form
      onSubmit={submit}
      noValidate
      aria-labelledby="edit-user-heading"
      className="flex flex-col gap-3 rounded border border-border bg-surface p-3"
    >
      <h2
        id="edit-user-heading"
        ref={heading}
        tabIndex={-1}
        className="font-semibold"
      >
        Edit {user.email}
      </h2>
      <label className="flex flex-col gap-1">
        <span>Name</span>
        <input
          value={name}
          maxLength={200}
          onChange={(e) => {
            setName(e.target.value);
          }}
          className={field}
        />
      </label>
      <fieldset className="flex flex-wrap gap-3">
        <legend>Roles</legend>
        {isSelf ? (
          <p className="text-text-muted">
            Your own roles are changed by another administrator.
          </p>
        ) : (
          roleKeys.map((key) => (
            <label key={key} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={roles.includes(key)}
                onChange={(e) => {
                  setRoles(
                    e.target.checked
                      ? [...roles, key]
                      : roles.filter((r) => r !== key),
                  );
                }}
              />
              {key}
            </label>
          ))
        )}
      </fieldset>
      {update.isError && (
        <p role="alert" className="text-critical">
          {problemText(update.error, "The user could not be saved.")}
        </p>
      )}
      <div className="flex gap-2">
        <button
          type="submit"
          className={button}
          disabled={update.isPending || !name.trim()}
        >
          Save
        </button>
        <button type="button" className={button} onClick={props.onClose}>
          Cancel
        </button>
      </div>
    </form>
  );
}
