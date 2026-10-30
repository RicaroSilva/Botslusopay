import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { RunsTable } from "./ui";

test("tabela de execuções mostra estado e marca 'Rever'", () => {
  render(
    <MemoryRouter>
      <RunsTable runs={[{ id: "r1", bot_key: "b", bot_name: "Bot X", status: "FAILED", trigger_source: "schedule",
        created_at: "2026-01-01T10:00:00Z", needs_review: true, failure_reason: "worker_lost" }]} />
    </MemoryRouter>,
  );
  expect(screen.getByText("Falhou")).toBeTruthy();
  expect(screen.getByText("Rever")).toBeTruthy();
  expect(screen.getByText("Worker perdido")).toBeTruthy();
  expect(screen.getByText("Agendamento")).toBeTruthy();
});
