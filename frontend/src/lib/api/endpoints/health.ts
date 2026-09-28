import { http } from '../client'
import type { HealthLiveResponse, HealthReadyResponse, HealthResponse } from '../types'

export const healthApi = {
  health: () => http.get<HealthResponse>('/health', undefined, { root: true }),
  live: () => http.get<HealthLiveResponse>('/health/live', undefined, { root: true }),
  ready: () => http.get<HealthReadyResponse>('/health/ready', undefined, { root: true }),
}
