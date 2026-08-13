import { BrowserRouter, Route, Routes } from 'react-router-dom'
import AppShell from '@/components/layout/AppShell'
import Console from '@/routes/Console'
import DataRoute from '@/routes/DataRoute'
import Rings from '@/routes/Rings'

export default function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<Console />} />
          <Route path="/rings" element={<Rings />} />
          <Route path="/data" element={<DataRoute />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  )
}
