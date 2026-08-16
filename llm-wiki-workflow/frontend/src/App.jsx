import { Routes, Route } from 'react-router-dom'
import Shell from './components/Shell'
import Home      from './pages/Home'
import WikiList  from './pages/WikiList'
import WikiPage  from './pages/WikiPage'
import Search    from './pages/Search'
import Log       from './pages/Log'
import Raw       from './pages/Raw'
import Tools     from './pages/Tools'
import Atlas     from './pages/Atlas'

export default function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/"        element={<Home />} />
        <Route path="/wiki"    element={<WikiList />} />
        <Route path="/wiki/*"  element={<WikiPage />} />
        <Route path="/search"  element={<Search />} />
        <Route path="/log"     element={<Log />} />
        <Route path="/raw"     element={<Raw />} />
        <Route path="/tools"   element={<Tools />} />
        <Route path="/atlas"   element={<Atlas />} />
      </Routes>
    </Shell>
  )
}
