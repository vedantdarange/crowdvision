export { CONTRACT_VERSION } from '@contract/types';
export const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1';
export const LEVELS = ['SAFE', 'WARNING', 'CRITICAL', 'NO_DATA'] as const;
