import { clean } from "./FlowEditor";

test("clean remove campos opcionais vazios e mantém passos aninhados", () => {
  const out = clean([
    { id: "a", type: "http_request", method: "GET", url: "https://x.pt", headers: {}, query: {}, credential: "",
      body_text: "", save_as: "r", expect_status: [200] },
    { id: "b", type: "foreach", items_expr: "r", item_variable: "item", parallel: 1, steps: [
      { id: "c", type: "email", credential: "smtp", to: ["a@b.pt", ""], cc: [], subject: "s", body: "b", attachments: [] },
    ] },
  ]);
  expect(out[0]).toEqual({ id: "a", type: "http_request", method: "GET", url: "https://x.pt", save_as: "r", expect_status: [200] });
  expect(clean([{ id: "f", type: "foreach", items_expr: "x", carry: ["total"], steps: [] }])[0].carry).toEqual(["total"]);
  expect(clean([{ id: "z", type: "set", variable: "v", value: "1", campo_novo: 5 }])[0].campo_novo).toBe(5);
  expect(out[1].steps).toEqual([{ id: "c", type: "email", credential: "smtp", to: ["a@b.pt"], subject: "s", body: "b" }]);
});
