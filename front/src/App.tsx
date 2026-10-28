import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import Layout from "./components/Layout";
import LoginPage from "./pages/LoginPage";
import MyBidsPage from "./pages/MyBidsPage";
import PainelPage from "./pages/PainelPage";
import ReceiptPage from "./pages/ReceiptPage";
import RegisterPage from "./pages/RegisterPage";
import RoomPage from "./pages/RoomPage";
import VitrinePage from "./pages/VitrinePage";
import WalletPage from "./pages/WalletPage";

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<VitrinePage />} />
            <Route path="/entrar" element={<LoginPage />} />
            <Route path="/registrar" element={<RegisterPage />} />
            <Route path="/carteira" element={<WalletPage />} />
            <Route path="/meus-lances" element={<MyBidsPage />} />
            <Route path="/painel" element={<PainelPage />} />
            <Route path="/comprovantes/:uuid" element={<ReceiptPage />} />
            <Route path="/lotes/:auctionId" element={<RoomPage />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
