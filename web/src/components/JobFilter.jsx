import { Search, Filter, SortAsc } from 'lucide-react'

export default function JobFilter({
  searchQuery, onSearchChange,
  scoreFilter, onScoreFilterChange,
  statusFilter, onStatusFilterChange,
  sortBy, onSortByChange,
}) {
  return (
    <div className="bg-white rounded-xl p-4 shadow-sm mb-6">
      <div className="flex flex-wrap gap-4 items-center">
        {/* Search */}
        <div className="flex-1 min-w-[200px] relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#494453]" />
          <input
            type="text"
            placeholder="Search jobs or companies..."
            value={searchQuery}
            onChange={e => onSearchChange(e.target.value)}
            className="w-full pl-10 pr-4 py-2 bg-[#f3f4f5] rounded-lg text-sm text-[#191c1d] placeholder:text-[#494453] focus:outline-none focus:ring-2 focus:ring-[#6B46C1]"
          />
        </div>

        {/* Score Filter */}
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-[#494453]" />
          <select
            value={scoreFilter}
            onChange={e => onScoreFilterChange(e.target.value)}
            className="px-3 py-2 bg-[#f3f4f5] rounded-lg text-sm text-[#191c1d] focus:outline-none focus:ring-2 focus:ring-[#6B46C1]"
          >
            <option value="all">All Scores</option>
            <option value="high">🔥 High (≥0.7)</option>
            <option value="medium">Medium (0.4-0.7)</option>
            <option value="low">Low (&lt;0.4)</option>
          </select>
        </div>

        {/* Status Filter */}
        <select
          value={statusFilter}
          onChange={e => onStatusFilterChange(e.target.value)}
          className="px-3 py-2 bg-[#f3f4f5] rounded-lg text-sm text-[#191c1d] focus:outline-none focus:ring-2 focus:ring-[#6B46C1]"
        >
          <option value="all">All Status</option>
          <option value="notified">Notified</option>
          <option value="applied">Applied</option>
          <option value="pending">Pending</option>
          <option value="interview">Interview</option>
        </select>

        {/* Sort */}
        <div className="flex items-center gap-2">
          <SortAsc className="w-4 h-4 text-[#494453]" />
          <select
            value={sortBy}
            onChange={e => onSortByChange(e.target.value)}
            className="px-3 py-2 bg-[#f3f4f5] rounded-lg text-sm text-[#191c1d] focus:outline-none focus:ring-2 focus:ring-[#6B46C1]"
          >
            <option value="date">Newest First</option>
            <option value="score">Highest Score</option>
            <option value="company">Company A-Z</option>
          </select>
        </div>
      </div>
    </div>
  )
}
