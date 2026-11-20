/** The Puck editor (lazy-loaded chunk; ADR-0005: pinned 0.24.0, `no-external.css`). */
import "@puckeditor/core/no-external.css";

import { Puck } from "@puckeditor/core";
import { useMemo } from "react";

import type { ReportField } from "./api";
import { reportConfig } from "./puckConfig";

export default function Editor(props: {
  fields: ReportField[];
  data: Record<string, unknown>;
  onChange: (data: Record<string, unknown>) => void;
}) {
  const config = useMemo(() => reportConfig(props.fields), [props.fields]);
  return (
    <div className="min-h-[70vh] rounded border border-border">
      <Puck
        config={config}
        data={props.data}
        onChange={(data) => {
          props.onChange(data);
        }}
        iframe={{ enabled: false }}
        headerTitle="Report layout"
        renderHeaderActions={() => (
          <span className="text-sm">Save with the button above</span>
        )}
      />
    </div>
  );
}
