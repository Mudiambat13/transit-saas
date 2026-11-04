import { isoToLocalInput, localInputToIso } from "../components/common";

describe("fuseaux horaires", () => {
  it("convertit l'heure locale de Lubumbashi (UTC+2) en UTC", () => {
    expect(localInputToIso("2026-11-03T08:00", "Africa/Lubumbashi")).toBe("2026-11-03T06:00:00.000Z");
  });
  it("fait l'aller-retour sans perte", () => {
    const iso = localInputToIso("2026-07-15T22:30", "Europe/Paris");
    expect(isoToLocalInput(iso, "Europe/Paris")).toBe("2026-07-15T22:30");
  });
});
