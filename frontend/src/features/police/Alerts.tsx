import { useEffect, useState, useRef } from 'react';
import { Link } from 'react-router';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import type { Alert, AlertDetail, AlertStatus, ApiOne } from '@contract/types';
import { apiClient, ApiRequestError } from '@/lib/apiClient';
import { queryKeys as k } from '@/lib/queryKeys';
import { relativeTime } from '@/lib/format';
import { useSession } from '@/features/auth';
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { LevelBadge } from '@/components/status/LevelBadge';
import { updateAlert, useDelay } from './data';

const targets = {
  acknowledge: 'ACKNOWLEDGED',
  respond: 'RESPONDING',
  resolve: 'RESOLVED',
} as const;
type Action = keyof typeof targets;
const available: Record<AlertStatus, Action[]> = {
  NEW: ['acknowledge', 'respond', 'resolve'],
  ACKNOWLEDGED: ['respond', 'resolve'],
  RESPONDING: ['resolve'],
  RESOLVED: [],
  AUTO_CLEARED: [],
};
export const label = (value: string) =>
  value[0]!.toUpperCase() + value.slice(1).toLowerCase().replaceAll('_', ' ');
type Selection = { alert: Alert; action: Action; trigger: HTMLElement };
export type Choose = (selection: Selection) => void;

export function Age({ ts }: { ts: string | null }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!ts) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [ts]);
  if (!ts) return <>No data yet</>;
  const absolute = new Date(ts).toLocaleString();
  return (
    <time dateTime={ts} tabIndex={0} title={absolute} className="police-time">
      {relativeTime(ts, now)}
      <span>{absolute}</span>
    </time>
  );
}
export function Status({ alert }: { alert: Alert }) {
  return (
    <div>
      {label(alert.status)}
      {alert.status === 'NEW' && !alert.condition_active && (
        <small className="review-chip">
          Condition cleared - awaiting review
        </small>
      )}
    </div>
  );
}
export function Actions({ alert, choose }: { alert: Alert; choose: Choose }) {
  return (
    <div className="police-actions">
      {available[alert.status].map((action) => (
        <Button
          key={action}
          variant="outline"
          onClick={(e) => choose({ alert, action, trigger: e.currentTarget })}
        >
          {label(action)}
        </Button>
      ))}
    </div>
  );
}
export function AlertCard({ alert, choose }: { alert: Alert; choose: Choose }) {
  return (
    <article className="alert-card">
      <Link
        className="inline-flex min-h-11 items-center"
        to={'/police/alerts/' + alert.id}
      >
        {alert.zone_name} · #{alert.id}
      </Link>
      <LevelBadge level={alert.level} />
      <Status alert={alert} />
      <Age ts={alert.created_at} />
      <Actions alert={alert} choose={choose} />
    </article>
  );
}
export function useAlertDialog() {
  const [selection, choose] = useState<Selection | null>(null);
  return {
    choose,
    dialog: selection && (
      <ActionDialog
        key={selection.alert.id + selection.action}
        selection={selection}
        close={() => choose(null)}
      />
    ),
  };
}
export function useAlertAction() {
  const client = useQueryClient();
  const generation = useRef(useSession.getState().generation).current;
  const sameSession = () => generation === useSession.getState().generation;
  return useMutation({
    mutationFn: ({
      alert,
      action,
      note = '',
    }: {
      alert: Alert;
      action: Action;
      note?: string;
    }) =>
      apiClient<ApiOne<Alert>>('/alerts/' + alert.id + '/' + action, {
        method: 'POST',
        body: note.trim() ? { note: note.trim() } : {},
      }),
    onMutate: async ({ alert, action }) => {
      await client.cancelQueries({ queryKey: ['alerts'] });
      const before =
        client.getQueryData<AlertDetail>(k.alertDetail(alert.id)) ?? alert;
      const pages = client.getQueriesData({
        queryKey: ['alerts'],
        predicate: (q) => typeof q.queryKey[1] === 'object',
      });
      if (sameSession())
        updateAlert(client, { ...before, status: targets[action] }, false);
      return {
        before,
        optimistic: client.getQueryData(k.alertDetail(alert.id)),
        pages: pages.map(([key, original]) => ({
          key,
          original,
          optimistic: client.getQueryData(key),
        })),
      };
    },
    onError: (error, { alert }, snapshot) => {
      if (!sameSession()) return;
      if (
        snapshot &&
        client.getQueryData(k.alertDetail(alert.id)) === snapshot.optimistic
      ) {
        // Restore exact page membership, including rows pushed off the page.
        // Only replace pages that received no intervening socket updates.
        const untouched = snapshot.pages.filter(
          (p) => client.getQueryData(p.key) === p.optimistic,
        );
        updateAlert(client, snapshot.before, false);
        for (const p of untouched) client.setQueryData(p.key, p.original);
      }
      toast.error(
        error instanceof ApiRequestError &&
          error.status === 409 &&
          error.code === 'INVALID_TRANSITION'
          ? 'Someone already updated this alert'
          : error.message,
      );
    },
    onSuccess: ({ data }) => {
      if (sameSession()) updateAlert(client, data, false);
    },
    onSettled: () => {
      if (sameSession())
        void client.invalidateQueries({ queryKey: ['alerts'] });
    },
  });
}
function ActionDialog({
  selection,
  close,
}: {
  selection: Selection;
  close: () => void;
}) {
  const { alert, action, trigger } = selection;
  const [note, setNote] = useState('');
  const user = useSession((s) => s.user);
  const delay = useDelay(action === 'resolve' && user?.role === 'admin');
  const mutation = useAlertAction();
  return (
    <Dialog
      open
      onOpenChange={(v) => {
        if (!v && !mutation.isPending) close();
      }}
    >
      <DialogContent
        onCloseAutoFocus={(e) => {
          e.preventDefault();
          (trigger.isConnected
            ? trigger
            : document.getElementById('main')
          )?.focus();
        }}
      >
        <DialogTitle>
          {label(action)} alert #{alert.id}
        </DialogTitle>
        <DialogDescription>
          {alert.zone_name}.{' '}
          {action === 'resolve' &&
            'A new alert is raised if the zone is still over the limit after ' +
              (delay.data
                ? delay.data.reraise_after_s + ' seconds.'
                : 'the re-raise delay configured in Settings.')}
        </DialogDescription>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!mutation.isPending)
              mutation.mutate({ alert, action, note }, { onSettled: close });
          }}
        >
          <label>
            Optional note
            <textarea
              className="block w-full rounded border bg-background p-2"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <div className="police-actions">
            <DialogClose asChild>
              <Button
                type="button"
                variant="outline"
                disabled={mutation.isPending}
              >
                Cancel
              </Button>
            </DialogClose>
            <Button disabled={mutation.isPending}>{label(action)}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
