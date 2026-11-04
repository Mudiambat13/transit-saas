import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "../services/auth";
import LoginPage from "../features/auth/LoginPage";

describe("LoginPage", () => {
  afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

  it("affiche l'erreur renvoyée par l'API en cas d'identifiants incorrects", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Email ou mot de passe incorrect.", code: "invalid_credentials" }), { status: 401 }));
    render(<MemoryRouter><AuthProvider><LoginPage /></AuthProvider></MemoryRouter>);
    await userEvent.type(screen.getByLabelText(/e-mail/i), "a@b.cd");
    await userEvent.type(screen.getByLabelText(/mot de passe/i), "mauvais");
    await userEvent.click(screen.getByRole("button", { name: /se connecter/i }));
    expect(await screen.findByText("Email ou mot de passe incorrect.")).toBeInTheDocument();
  });
});
