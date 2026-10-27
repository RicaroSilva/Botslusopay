import { fmtDuration, STATUS_LABEL } from "./format";

test("todos os estados têm etiqueta", () => {
  for (const s of ["PENDING", "WAITING_APPROVAL", "QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]) {
    expect(STATUS_LABEL[s as keyof typeof STATUS_LABEL]).toBeTruthy();
  }
});

test("duração", () => {
  expect(fmtDuration("2026-01-01T10:00:00Z", "2026-01-01T10:00:42Z")).toBe("42s");
  expect(fmtDuration("2026-01-01T10:00:00Z", "2026-01-01T11:05:00Z")).toBe("1h 5m");
  expect(fmtDuration(null, null)).toBe("—");
});
