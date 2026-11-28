import { useDeferredValue, useState } from 'react';
import { Age } from '@/features/police/Alerts';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ManagementPage, Pager } from './ManagementLayout';
import { useAudit } from './managementApi';
const actions =
  'USER_CREATED USER_UPDATED ZONE_CREATED ZONE_UPDATED ZONE_DELETED SOURCE_CREATED SOURCE_UPDATED SOURCE_DELETED SETTINGS_UPDATED ALERT_ACKNOWLEDGED ALERT_RESPONDING ALERT_RESOLVED ADVISORY_CREATED ADVISORY_RETRACTED REPORT_REVIEWED'.split(
    ' ',
  );
function Audit() {
  const [filters, set] = useState({ action: '', actor_id: '', page: '1' });
  const { data } = useAudit(useDeferredValue(filters));
  return (
    <>
      <div className="police-filters">
        <label>
          Action
          <select
            value={filters.action}
            onChange={(e) =>
              set({ ...filters, action: e.target.value, page: '1' })
            }
          >
            <option value="">All actions</option>
            {actions.map((a) => (
              <option key={a}>{a}</option>
            ))}
          </select>
        </label>
        <label>
          Actor ID
          <input
            type="number"
            min="1"
            value={filters.actor_id}
            onChange={(e) => {
              if (e.target.validity.valid)
                set({ ...filters, actor_id: e.target.value, page: '1' });
            }}
          />
        </label>
      </div>
      {data.data.length ? (
        <Table>
          <TableHeader>
            <TableRow>
              {['Time', 'Actor', 'Action', 'Entity', 'Details'].map((h) => (
                <TableHead key={h}>{h}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.data.map((row) => (
              <TableRow key={row.id}>
                <TableCell>
                  <Age ts={row.created_at} />
                </TableCell>
                <TableCell>
                  {row.actor
                    ? row.actor.name + ' (#' + row.actor.id + ')'
                    : 'System'}
                </TableCell>
                <TableCell>{row.action}</TableCell>
                <TableCell>
                  {row.entity_type}{' '}
                  {row.entity_id !== null && '#' + row.entity_id}
                </TableCell>
                <TableCell>
                  {Object.keys(row.data).length ? (
                    <details>
                      <summary>View details</summary>
                      <pre className="max-w-sm whitespace-pre-wrap break-all">
                        {JSON.stringify(row.data, null, 2)}
                      </pre>
                    </details>
                  ) : (
                    '—'
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : (
        <p>No audit entries match. Try another action or actor.</p>
      )}
      <Pager
        data={data.pagination}
        setPage={(p) => set({ ...filters, page: String(p) })}
      />
    </>
  );
}
export function Component() {
  return (
    <ManagementPage title="Audit log">
      <Audit />
    </ManagementPage>
  );
}
