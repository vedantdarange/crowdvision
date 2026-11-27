type Filters = Readonly<Record<string, string | number | boolean | undefined>>;
export const queryKeys = {
  config: ['config'] as const,
  help: ['help'] as const,
  zones: {
    live: ['zones', 'live'] as const,
    public: (id: number) => ['zones', 'public', id] as const,
    list: ['zones', 'list'] as const,
    detail: (id: number) => ['zones', 'detail', id] as const,
    history: (id: number, range: string) =>
      ['zones', 'history', id, range] as const,
  },
  alerts: (filters: Filters) => ['alerts', filters] as const,
  alertDetail: (id: number) => ['alerts', 'detail', id] as const,
  advisories: (zoneId: number | 'all' = 'all') =>
    ['advisories', zoneId] as const,
  reports: (filters: Filters) => ['reports', filters] as const,
  myReports: ['reports', 'mine'] as const,
  sources: (zoneId: number | 'all' = 'all') => ['sources', zoneId] as const,
  users: (filters: Filters) => ['users', filters] as const,
  settings: ['settings'] as const,
  analytics: (range: string) => ['analytics', range] as const,
  audit: (filters: Filters) => ['audit', filters] as const,
};
