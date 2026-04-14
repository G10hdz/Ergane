import { useState } from 'react'
import Sidebar from './components/Sidebar'
import MetricCard from './components/MetricCard'
import JobTable from './components/JobTable'
import JobFilter from './components/JobFilter'

// Mock data for demonstration
const mockJobs = [
  { id: 1, title: 'Senior DevOps Engineer', company: 'Clip', location: 'CDMX, Mexico', score: 0.85, source: 'Target Companies', status: 'Notified', date: '2026-04-12', tags: ['AWS', 'Python', 'Kubernetes'] },
  { id: 2, title: 'Cloud Engineer', company: 'Rappi', location: 'Remote, LATAM', score: 0.72, source: 'GetOnBrd', status: 'Applied', date: '2026-04-11', tags: ['AWS', 'Terraform', 'Docker'] },
  { id: 3, title: 'MLOps Jr', company: 'Bitso', location: 'CDMX, Mexico', score: 0.55, source: 'TechJobsMX', status: 'Pending', date: '2026-04-10', tags: ['Python', 'Docker', 'ML'] },
  { id: 4, title: 'Backend Developer', company: 'Konfío', location: 'Remote, Mexico', score: 0.48, source: 'GetOnBrd', status: 'Notified', date: '2026-04-09', tags: ['Python', 'FastAPI', 'PostgreSQL'] },
  { id: 5, title: 'Platform Engineer', company: 'Hugging Face', location: 'Remote, Global', score: 0.91, source: 'Target Companies', status: 'Interview', date: '2026-04-08', tags: ['Python', 'Kubernetes', 'AI'] },
  { id: 6, title: 'DevOps Specialist', company: 'Manpower', location: 'CDMX, Mexico', score: 0.22, source: 'OCC', status: 'Notified', date: '2026-04-07', tags: ['Linux', 'Bash'] },
  { id: 7, title: 'AI Engineer', company: 'Cohere', location: 'Remote, Global', score: 0.78, source: 'Target Companies', status: 'Applied', date: '2026-04-06', tags: ['Python', 'LLM', 'RAG'] },
  { id: 8, title: 'SRE Engineer', company: 'Canonical', location: 'Remote, Global', score: 0.65, source: 'WeWorkRemotely', status: 'Pending', date: '2026-04-05', tags: ['Linux', 'AWS', 'Terraform'] },
]

function App() {
  const [activePage, setActivePage] = useState('jobs')
  const [searchQuery, setSearchQuery] = useState('')
  const [scoreFilter, setScoreFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [sortBy, setSortBy] = useState('date')

  // Filter and sort jobs
  const filteredJobs = mockJobs
    .filter(job => {
      const matchesSearch = searchQuery === '' || 
        job.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        job.company.toLowerCase().includes(searchQuery.toLowerCase())
      const matchesScore = scoreFilter === 'all' ||
        (scoreFilter === 'high' && job.score >= 0.7) ||
        (scoreFilter === 'medium' && job.score >= 0.4 && job.score < 0.7) ||
        (scoreFilter === 'low' && job.score < 0.4)
      const matchesStatus = statusFilter === 'all' || job.status.toLowerCase() === statusFilter.toLowerCase()
      return matchesSearch && matchesScore && matchesStatus
    })
    .sort((a, b) => {
      if (sortBy === 'date') return new Date(b.date) - new Date(a.date)
      if (sortBy === 'score') return b.score - a.score
      if (sortBy === 'company') return a.company.localeCompare(b.company)
      return 0
    })

  const metrics = {
    total: mockJobs.length,
    applied: mockJobs.filter(j => j.status === 'Applied').length,
    pending: mockJobs.filter(j => j.status === 'Pending').length,
    interviews: mockJobs.filter(j => j.status === 'Interview').length,
  }

  return (
    <div className="flex h-screen bg-[#f8f9fa]">
      <Sidebar activePage={activePage} onNavigate={setActivePage} />
      
      <main className="flex-1 overflow-auto">
        <div className="p-8">
          {/* Header */}
          <header className="mb-8">
            <h1 className="text-3xl font-bold text-[#191c1d] tracking-tight">
              {activePage === 'jobs' && 'Job Dashboard'}
              {activePage === 'applications' && 'Applications'}
              {activePage === 'profiles' && 'User Profiles'}
              {activePage === 'analytics' && 'Analytics'}
            </h1>
            <p className="text-[#494453] mt-1">
              {activePage === 'jobs' && 'Track and manage your job opportunities'}
              {activePage === 'applications' && 'View your application pipeline'}
              {activePage === 'profiles' && 'Manage skills and preferences'}
              {activePage === 'analytics' && 'Pipeline metrics and performance'}
            </p>
          </header>

          {activePage === 'jobs' && (
            <>
              {/* Metric Cards */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                <MetricCard label="Total Jobs" value={metrics.total} icon="📊" color="#6B46C1" />
                <MetricCard label="Applied" value={metrics.applied} icon="✅" color="#10b981" />
                <MetricCard label="Pending" value={metrics.pending} icon="⏳" color="#f59e0b" />
                <MetricCard label="Interviews" value={metrics.interviews} icon="🎯" color="#3b82f6" />
              </div>

              {/* Filters */}
              <JobFilter
                searchQuery={searchQuery}
                onSearchChange={setSearchQuery}
                scoreFilter={scoreFilter}
                onScoreFilterChange={setScoreFilter}
                statusFilter={statusFilter}
                onStatusFilterChange={setStatusFilter}
                sortBy={sortBy}
                onSortByChange={setSortBy}
              />

              {/* Job Table */}
              <JobTable jobs={filteredJobs} />
            </>
          )}

          {activePage === 'applications' && (
            <div className="bg-white rounded-xl p-8 shadow-sm">
              <h2 className="text-xl font-semibold text-[#191c1d] mb-4">Application Pipeline</h2>
              <div className="space-y-4">
                {mockJobs.filter(j => j.status === 'Applied').map(job => (
                  <div key={job.id} className="flex items-center justify-between p-4 bg-[#f3f4f5] rounded-lg">
                    <div>
                      <h3 className="font-medium text-[#191c1d]">{job.title}</h3>
                      <p className="text-sm text-[#494453]">{job.company} • {job.location}</p>
                    </div>
                    <div className="text-right">
                      <div className="text-sm font-semibold text-[#6B46C1]">Score: {job.score.toFixed(2)}</div>
                      <div className="text-xs text-[#494453]">{job.date}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activePage === 'profiles' && (
            <div className="bg-white rounded-xl p-8 shadow-sm">
              <h2 className="text-xl font-semibold text-[#191c1d] mb-4">User Profiles</h2>
              <p className="text-[#494453] mb-6">Create and manage user profiles for personalized job matching.</p>
              <div className="grid gap-6 md:grid-cols-2">
                <div className="p-6 bg-[#f3f4f5] rounded-lg">
                  <h3 className="font-semibold text-[#191c1d] mb-2">DevOps / Cloud Engineer</h3>
                  <p className="text-sm text-[#494453] mb-3">Skills: Python, AWS, Terraform, Docker, LangChain</p>
                  <div className="flex gap-2">
                    <span className="px-2 py-1 text-xs bg-[#e9ddff] text-[#532aa8] rounded">min_score: 0.15</span>
                    <span className="px-2 py-1 text-xs bg-[#f3f4f5] text-[#494453] rounded">remote_preferred</span>
                  </div>
                </div>
                <div className="p-6 border-2 border-dashed border-[#cbc3d5] rounded-lg flex items-center justify-center cursor-pointer hover:border-[#6B46C1] transition-colors">
                  <div className="text-center">
                    <div className="text-3xl text-[#6B46C1] mb-2">+</div>
                    <p className="text-sm text-[#494453]">Add new profile</p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {activePage === 'analytics' && (
            <div className="space-y-6">
              <div className="grid gap-6 md:grid-cols-2">
                <div className="bg-white rounded-xl p-6 shadow-sm">
                  <h3 className="font-semibold text-[#191c1d] mb-4">Jobs by Source</h3>
                  <div className="space-y-3">
                    {[
                      { source: 'GetOnBrd', count: 130, pct: 35 },
                      { source: 'Target Companies', count: 85, pct: 23 },
                      { source: 'WeWorkRemotely', count: 80, pct: 22 },
                      { source: 'TechJobsMX', count: 50, pct: 14 },
                      { source: 'OCC', count: 20, pct: 6 },
                    ].map(item => (
                      <div key={item.source}>
                        <div className="flex justify-between text-sm mb-1">
                          <span className="text-[#191c1d]">{item.source}</span>
                          <span className="text-[#494453]">{item.count} jobs</span>
                        </div>
                        <div className="h-2 bg-[#f3f4f5] rounded-full overflow-hidden">
                          <div className="h-full bg-[#6B46C1] rounded-full" style={{ width: `${item.pct}%` }} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="bg-white rounded-xl p-6 shadow-sm">
                  <h3 className="font-semibold text-[#191c1d] mb-4">Score Distribution</h3>
                  <div className="flex items-end gap-2 h-40">
                    {[
                      { range: '0.0-0.2', count: 120, color: '#e5e7eb' },
                      { range: '0.2-0.4', count: 85, color: '#d1d5db' },
                      { range: '0.4-0.6', count: 65, color: '#9ca3af' },
                      { range: '0.6-0.8', count: 35, color: '#6B46C1' },
                      { range: '0.8-1.0', count: 12, color: '#532aa8' },
                    ].map(item => {
                      const maxCount = 120
                      const height = (item.count / maxCount) * 100
                      return (
                        <div key={item.range} className="flex-1 flex flex-col items-center">
                          <div className="text-xs text-[#494453] mb-1">{item.count}</div>
                          <div
                            className="w-full rounded-t"
                            style={{ height: `${height}%`, backgroundColor: item.color }}
                          />
                          <div className="text-xs text-[#494453] mt-2 text-center">{item.range}</div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              </div>

              <div className="bg-white rounded-xl p-6 shadow-sm">
                <h3 className="font-semibold text-[#191c1d] mb-4">Pipeline Metrics</h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
                  <div>
                    <div className="text-sm text-[#494453]">Total Runs</div>
                    <div className="text-3xl font-bold text-[#191c1d]">47</div>
                  </div>
                  <div>
                    <div className="text-sm text-[#494453]">Avg Jobs/Run</div>
                    <div className="text-3xl font-bold text-[#191c1d]">185</div>
                  </div>
                  <div>
                    <div className="text-sm text-[#494453]">Notification Rate</div>
                    <div className="text-3xl font-bold text-[#191c1d]">23%</div>
                  </div>
                  <div>
                    <div className="text-sm text-[#494453]">Application Rate</div>
                    <div className="text-3xl font-bold text-[#191c1d]">12%</div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}

export default App
