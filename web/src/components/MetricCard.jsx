export default function MetricCard({ label, value, icon, color }) {
  return (
    <div className="bg-white rounded-xl p-6 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-center justify-between mb-4">
        <span className="text-2xl">{icon}</span>
        <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${color}20` }}>
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: color }} />
        </div>
      </div>
      <div className="text-3xl font-bold text-[#191c1d] mb-1">{value}</div>
      <div className="text-sm text-[#494453]">{label}</div>
    </div>
  )
}
