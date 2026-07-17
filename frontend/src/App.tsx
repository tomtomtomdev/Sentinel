import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { AddMonitorPage } from "./pages/AddMonitorPage";
import { DashboardPage } from "./pages/DashboardPage";

/** Route table without providers — tests mount this inside a MemoryRouter. */
export function AppRoutes() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/monitors" replace />} />
        <Route path="/monitors" element={<DashboardPage />} />
        <Route path="/monitors/new" element={<AddMonitorPage />} />
      </Routes>
    </Layout>
  );
}

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
