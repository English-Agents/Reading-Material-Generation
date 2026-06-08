import { NavLink, Outlet } from "react-router-dom";

export default function Layout() {
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `px-3 py-2 rounded-md text-sm font-medium transition-colors ${
      isActive
        ? "bg-indigo-600 text-white"
        : "text-slate-600 hover:bg-slate-100"
    }`;

  return (
    <div className="min-h-screen flex flex-col">
      <nav className="bg-white border-b border-slate-200 px-6 py-3 flex items-center gap-4 shadow-sm">
        <span className="font-bold text-indigo-700 text-lg tracking-tight mr-4">
          RMG
        </span>
        <NavLink to="/" className={linkClass} end>
          Generate
        </NavLink>
        <NavLink to="/ops" className={linkClass}>
          Dashboard
        </NavLink>
      </nav>
      <main className="flex-1 p-6 max-w-6xl mx-auto w-full">
        <Outlet />
      </main>
    </div>
  );
}
