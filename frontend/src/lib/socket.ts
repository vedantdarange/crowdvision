import { io, type Socket } from 'socket.io-client';
import type {
  ServerToClientEvents,
  ClientToServerEvents,
} from '@contract/types';
export const socket: Socket<ServerToClientEvents, ClientToServerEvents> = io({
  autoConnect: false,
});
