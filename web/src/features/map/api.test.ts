import { describe, expect, it } from "vitest";

import { interestFilters, MAX_JURISDICTIONS } from "./api";

const options = (members: string[]) => ({
  facets: [],
  jurisdictions: [],
  regions: [
    { key: "150", label: "Europe", members },
    { key: "142", label: "Asia", members: ["CN", "JP"] },
  ],
});

describe("interest filters (M11.1)", () => {
  it("combines jurisdictions and region members as one any-of list", () => {
    expect(
      interestFilters(
        {
          jurisdictions: ["CN"],
          regions: ["150"],
          terms: { topic: ["ai"], industry: [] },
        },
        options(["DE", "EU"]),
      ),
    ).toEqual({ jurisdictions: ["CN", "DE", "EU"], terms: { topic: ["ai"] } });
  });

  it("sends the regions alone when the members pass the cap", () => {
    const many = Array.from(
      { length: MAX_JURISDICTIONS },
      (_, n) => `J${String(n)}`,
    );
    expect(
      interestFilters(
        { jurisdictions: ["CN"], regions: ["150"], terms: {} },
        options(many),
      ),
    ).toEqual({ regions: ["150"] });
  });

  it("without the options, never sends jurisdictions and regions together", () => {
    expect(
      interestFilters({ jurisdictions: ["CN"], regions: ["150"], terms: {} }),
    ).toEqual({ jurisdictions: ["CN"] });
    expect(
      interestFilters({ jurisdictions: [], regions: ["150"], terms: {} }),
    ).toEqual({ regions: ["150"] });
    expect(interestFilters(undefined)).toEqual({});
  });
});
