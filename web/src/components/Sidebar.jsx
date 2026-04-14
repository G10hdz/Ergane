import { Briefcase, CheckSquare, Users, BarChart3, Settings } from 'lucide-react'

const navItems = [
  { id: 'jobs', label: 'Jobs', icon: Briefcase },
  { id: 'applications', label: 'Applications', icon: CheckSquare },
  { id: 'profiles', label: 'Profiles', icon: Users },
  { id: 'analytics', label: 'Analytics', icon: BarChart3 },
  { id: 'settings', label: 'Settings', icon: Settings },
]

export default function Sidebar({ activePage, onNavigate }) {
  return (
    <aside className="w-64 bg-[#f3f4f5] border-r border-[#e7e8e9] flex flex-col">
      {/* Logo */}
      <div className="p-6 border-b border-[#e7e8e9]">
        <h1 className="text-xl font-bold text-[#532aa8]">🚀 Ergane</h1>
        <p className="text-xs text-[#494453] mt-1">Job Search Assistant</p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-1">
        {navItems.map(item => {
          const Icon = item.icon
          const isActive = activePage === item.id
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all ${
                isActive
                  ? 'bg-[#6B46C1] text-white shadow-sm'
                  : 'text-[#494453] hover:bg-[#e7e8e9] hover:text-[#191c1d]'
              }`}
            >
              <Icon className="w-5 h-5" />
              {item.label}
            </button>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="p-4 border-t border-[#e7e8e9]">
        <div className="text-xs text-[#494453]">
          <p>Ergane v1.0.0</p>
          <p className="mt-1">MIT License</p>
        </div>
      </div>
    </aside>
  )
}
