import { describe, expect, it } from "vitest";
import { clean } from "./pages/FlowEditor";

describe("clean (limpeza dos passos antes de gravar/converter)", () => {
  it("mantém o valor vazio de 'Definir variável'", () => {
    const out = clean([{ id: "s1", type: "set", name: "Segredo (removido)", variable: "vSMTPPass", value: "" }]);
    expect(out[0]).toEqual({ id: "s1", type: "set", name: "Segredo (removido)", variable: "vSMTPPass", value: "" });
  });
  it("não acrescenta valor quando há expressão", () => {
    const out = clean([{ id: "s1", type: "set", variable: "x", value: "", expr: "1 + 1" }]);
    expect(out[0].value).toBeUndefined();
    expect(out[0].expr).toBe("1 + 1");
  });
  it("mantém campos desconhecidos (ex.: carry) e limpa os vazios", () => {
    const out = clean([{ id: "f", type: "foreach", items_expr: "l", item_variable: "i", carry: ["t"], name: "", steps: [] }]);
    expect(out[0].carry).toEqual(["t"]);
    expect("name" in out[0]).toBe(false);
  });
});
