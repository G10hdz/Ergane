import { ExternalLink } from 'lucide-react'

function ScoreBadge({ score }) {
  const isHigh = score >= 0.7
  const isMedium = score >= 0.4 && score < 0.7
  const isLow = score < 0.4

  let bgColor, textColor, label
  if (isHigh) {
    bgColor = 'bg-red-100'
    textColor = 'text-red-700'
    label = '🔥'
  } else if (isMedium) {
    bgColor = 'bg-orange-100'
    textColor = 'text-orange-700'
    label = ''
  } else {
    bgColor = 'bg-green-100'
    textColor = 'text-green-700'
    label = ''
  }

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-1 ${bgColor} ${textColor} text-xs font-semibold rounded`}>
      {label} {score.toFixed(2)}
    </span>
  )
}

function StatusBadge({ status }) {
  const styles = {
    Notified: 'bg-purple-100 text-purple-700',
    Applied: 'bg-green-100 text-green-700',
    Pending: 'bg-yellow-100 text-yellow-700',
    Interview: 'bg-blue-100 text-blue-700',
  }

  return (
    <span className={`px-2 py-1 ${styles[status] || 'bg-gray-100 text-gray-700'} text-xs font-semibold rounded`}>
      {status}
    </span>
  )
}

export default function JobTable({ jobs }) {
  if (jobs.length === 0) {
    return (
      <div className="bg-white rounded-xl p-12 shadow-sm text-center">
        <div className="text-4xl mb-4">📭</div>
        <h3 className="text-lg font-semibold text-[#191c1d] mb-2">No jobs found</h3>
        <p className="text-[#494453]">Try adjusting your filters or run the scraper to find new opportunities.</p>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-xl shadow-sm overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="bg-[#f3f4f5]">
              <th className="text-left px-6 py-4 text-xs font-semibold text-[#494453] uppercase tracking-wider">Job</th>
              <th className="text-left px-6 py-4 text-xs font-semibold text-[#494453] uppercase tracking-wider">Location</th>
              <th className="text-left px-6 py-4 text-xs font-semibold text-[#494453] uppercase tracking-wider">Score</th>
              <th className="text-left px-6 py-4 text-xs font-semibold text-[#494453] uppercase tracking-wider">Source</th>
              <th className="text-left px-6 py-4 text-xs font-semibold text-[#494453] uppercase tracking-wider">Status</th>
              <th className="text-left px-6 py-4 text-xs font-semibold text-[#494453] uppercase tracking-wider">Date</th>
              <th className="text-left px-6 py-4 text-xs font-semibold text-[#494453] uppercase tracking-wider">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#e7e8e9]">
            {jobs.map(job => (
              <tr key={job.id} className="hover:bg-[#f8f9fa] transition-colors">
                <td className="px-6 py-4">
                  <div className="font-medium text-[#191c1d]">{job.title}</div>
                  <div className="text-sm text-[#494453]">{job.company}</div>
                  {job.tags && job.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-2">
                      {job.tags.slice(0, 3).map(tag => (
                        <span key={tag} className="px-2 py-0.5 bg-[#e9ddff] text-[#532aa8] text-xs rounded">
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                </td>
                <td className="px-6 py-4 text-sm text-[#494453]">{job.location}</td>
                <td className="px-6 py-4">
                  <ScoreBadge score={job.score} />
                </td>
                <td className="px-6 py-4 text-sm text-[#494453]">{job.source}</td>
                <td className="px-6 py-4">
                  <StatusBadge status={job.status} />
                </td>
                <td className="px-6 py-4 text-sm text-[#494453]">{job.date}</td>
                <td className="px-6 py-4">
                  <button className="p-2 hover:bg-[#e7e8e9] rounded-lg transition-colors" title="View details">
                    <ExternalLink className="w-4 h-4 text-[#494453]" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      <div className="px-6 py-4 bg-[#f8f9fa] border-t border-[#e7e8e9]">
        <div className="text-sm text-[#494453]">
          Showing {jobs.length} of {jobs.length} jobs
        </div>
      </div>
    </div>
  )
}
