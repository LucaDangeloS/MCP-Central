import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from '@/store/auth'
import { Layout } from '@/components/Layout'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import Login from '@/pages/Login'
import Dashboard from '@/pages/Dashboard'
import Servers from '@/pages/Servers'
import Groups from '@/pages/Groups'
import ApiKeys from '@/pages/ApiKeys'
import Logs from '@/pages/Logs'
import Upload from '@/pages/Upload'
import Endpoints from '@/pages/Endpoints'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
          <Route path="servers" element={<ErrorBoundary><Servers /></ErrorBoundary>} />
          <Route path="groups" element={<ErrorBoundary><Groups /></ErrorBoundary>} />
          <Route path="keys" element={<ErrorBoundary><ApiKeys /></ErrorBoundary>} />
          <Route path="logs" element={<ErrorBoundary><Logs /></ErrorBoundary>} />
          <Route path="upload" element={<ErrorBoundary><Upload /></ErrorBoundary>} />
          <Route path="endpoints" element={<ErrorBoundary><Endpoints /></ErrorBoundary>} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
