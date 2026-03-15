import { useState, useEffect } from 'react'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  ArcElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js'
import { Bar, Line, Doughnut } from 'react-chartjs-2'

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  ArcElement,
  Title,
  Tooltip,
  Legend,
)

interface ScoreBucket {
  bucket: string
  count: number
}

interface PassRate {
  task: string
  avg_score: number
  attempts: number
}

interface TimelineEntry {
  date: string
  submissions: number
}

interface GroupEntry {
  group: string
  avg_score: number
  students: number
}

function Dashboard({ token }: { token: string }) {
  const [lab, setLab] = useState('lab-04')
  const [scores, setScores] = useState<ScoreBucket[]>([])
  const [passRates, setPassRates] = useState<PassRate[]>([])
  const [timeline, setTimeline] = useState<TimelineEntry[]>([])
  const [groups, setGroups] = useState<GroupEntry[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    const headers = { Authorization: `Bearer ${token}` }

    Promise.all([
      fetch(`/analytics/scores?lab=${lab}`, { headers }).then((r) => r.json()),
      fetch(`/analytics/pass-rates?lab=${lab}`, { headers }).then((r) => r.json()),
      fetch(`/analytics/timeline?lab=${lab}`, { headers }).then((r) => r.json()),
      fetch(`/analytics/groups?lab=${lab}`, { headers }).then((r) => r.json()),
    ])
      .then(([s, p, t, g]: [ScoreBucket[], PassRate[], TimelineEntry[], GroupEntry[]]) => {
        setScores(s)
        setPassRates(p)
        setTimeline(t)
        setGroups(g)
        setError('')
      })
      .catch((err: Error) => setError(err.message))
  }, [token, lab])

  if (error) return <p>Error loading analytics: {error}</p>

  const scoreData = {
    labels: scores.map((s) => s.bucket),
    datasets: [
      {
        label: 'Students',
        data: scores.map((s) => s.count),
        backgroundColor: ['#ef4444', '#f59e0b', '#3b82f6', '#22c55e'],
      },
    ],
  }

  const timelineData = {
    labels: timeline.map((t) => t.date),
    datasets: [
      {
        label: 'Submissions',
        data: timeline.map((t) => t.submissions),
        borderColor: '#3b82f6',
        tension: 0.3,
      },
    ],
  }

  const groupData = {
    labels: groups.map((g) => g.group),
    datasets: [
      {
        label: 'Avg Score',
        data: groups.map((g) => g.avg_score),
        backgroundColor: '#3b82f6',
      },
    ],
  }

  const passRateData = {
    labels: passRates.map((p) => p.task),
    datasets: [
      {
        data: passRates.map((p) => p.avg_score),
        backgroundColor: ['#22c55e', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6'],
      },
    ],
  }

  return (
    <div>
      <div className="lab-selector">
        <label>Lab: </label>
        <select value={lab} onChange={(e) => setLab(e.target.value)}>
          {['lab-01', 'lab-02', 'lab-03', 'lab-04', 'lab-05', 'lab-06'].map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>
      </div>

      <div className="charts-grid">
        <div className="chart-card">
          <h3>Score Distribution</h3>
          <Bar data={scoreData} options={{ plugins: { legend: { display: false } } }} />
        </div>

        <div className="chart-card">
          <h3>Submissions Timeline</h3>
          <Line data={timelineData} />
        </div>

        <div className="chart-card">
          <h3>Group Performance</h3>
          <Bar data={groupData} options={{ plugins: { legend: { display: false } } }} />
        </div>

        <div className="chart-card">
          <h3>Task Pass Rates</h3>
          <Doughnut data={passRateData} />
        </div>
      </div>

      {passRates.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Task</th>
              <th>Avg Score</th>
              <th>Attempts</th>
            </tr>
          </thead>
          <tbody>
            {passRates.map((p) => (
              <tr key={p.task}>
                <td>{p.task}</td>
                <td>{p.avg_score}</td>
                <td>{p.attempts}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export default Dashboard
