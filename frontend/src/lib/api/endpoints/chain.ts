import { http, seg } from '../client'
import type {
  AliasSubmitRequest,
  BlockchainTransaction,
  ChainPrepareRequest,
  FundingPrepareRequest,
  FundingView,
  Page,
  PageParams,
  PaymentRecord,
  PaymentsParams,
  PayoutPrepareRequest,
  PreparedTransaction,
  TransactionSubmitRequest,
} from '../types'

export const chainApi = {
  prepare: (bountyId: string, body: ChainPrepareRequest) =>
    http.post<PreparedTransaction>(`/bounties/${seg(bountyId)}/chain/prepare`, body),
}

export const fundingApi = {
  prepare: (bountyId: string, body: FundingPrepareRequest) =>
    http.post<PreparedTransaction>(`/bounties/${seg(bountyId)}/funding/prepare`, body),
  submit: (bountyId: string, body: AliasSubmitRequest) =>
    http.post<BlockchainTransaction>(`/bounties/${seg(bountyId)}/funding/submit`, body),
  get: (bountyId: string) => http.get<FundingView>(`/bounties/${seg(bountyId)}/funding`),
}

export const payoutsApi = {
  prepare: (bountyId: string, body: PayoutPrepareRequest) =>
    http.post<PreparedTransaction>(`/bounties/${seg(bountyId)}/payouts/prepare`, body),
  submit: (bountyId: string, body: AliasSubmitRequest) =>
    http.post<BlockchainTransaction>(`/bounties/${seg(bountyId)}/payouts/submit`, body),
}

export const transactionsApi = {
  /** Generic submit for any prepared action. */
  submit: (transactionId: string, body: TransactionSubmitRequest) =>
    http.post<BlockchainTransaction>(`/transactions/${seg(transactionId)}/submit`, body),
  forBounty: (bountyId: string) =>
    http.get<BlockchainTransaction[]>(`/bounties/${seg(bountyId)}/transactions`),
  mine: (params?: PageParams) => http.get<Page<BlockchainTransaction>>('/transactions/me', params),
  /** Accepts internal UUID or hash. */
  get: (idOrHash: string) => http.get<BlockchainTransaction>(`/transactions/${seg(idOrHash)}`),
}

export const paymentsApi = {
  mine: (params?: PaymentsParams) => http.get<Page<PaymentRecord>>('/payments/me', params),
}
