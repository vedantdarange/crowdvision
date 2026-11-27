import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';
// jsdom cannot scroll; browser navigation is checked separately in the live UI.
if (typeof window !== 'undefined') window.scrollTo = vi.fn();
afterEach(cleanup);
