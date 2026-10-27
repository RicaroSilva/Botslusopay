import { ApiError, api, qs } from "./api";

test("qs ignora vazios", () => {
  expect(qs({ a: "1", b: "", c: undefined, d: 0 })).toBe("?a=1&d=0");
});

test("pedidos enviam cabeçalho CSRF e convertem erros", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ detail: "já existe uma execução ativa deste bot", code: "conflicting_run" }), { status: 409 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  await expect(api.post("/api/bots/x/run", {})).rejects.toBeInstanceOf(ApiError);
  const [, init] = fetchMock.mock.calls[0];
  expect(init.headers["X-Requested-With"]).toBe("botmanager");
  expect(init.credentials).toBe("same-origin");
});
