import { Badge } from '@/components/ui/badge'
import type { ApplicationStatus, PaymentStatus, SubmissionStatus } from '@/lib/api/types'
import { APPLICATION_STATUS_LABELS, PAYMENT_STATUS_LABELS, SUBMISSION_STATUS_LABELS } from '@/lib/format'

type V = 'success' | 'warning' | 'danger' | 'info' | 'muted' | 'cyan'

const APP: Record<ApplicationStatus, V> = {
  PENDING: 'info',
  ACCEPTED: 'success',
  REJECTED: 'danger',
  WITHDRAWN: 'muted',
}
const SUB: Record<SubmissionStatus, V> = {
  SUBMITTED: 'info',
  REVISION_REQUESTED: 'warning',
  RESUBMITTED: 'cyan',
  APPROVED: 'success',
  REJECTED: 'danger',
}
const PAY: Record<PaymentStatus, V> = {
  NOT_REQUIRED: 'muted',
  CREATED: 'warning',
  SIGNATURE_REQUIRED: 'warning',
  SUBMITTED: 'info',
  CONFIRMED: 'success',
  FAILED: 'danger',
  REFUND_PENDING: 'warning',
  REFUNDED: 'muted',
}

export function ApplicationStatusBadge({ status }: { status: ApplicationStatus }) {
  return <Badge variant={APP[status]}>{APPLICATION_STATUS_LABELS[status]}</Badge>
}

export function SubmissionStatusBadge({ status }: { status: SubmissionStatus }) {
  return <Badge variant={SUB[status]}>{SUBMISSION_STATUS_LABELS[status]}</Badge>
}

export function PaymentStatusBadge({ status }: { status: PaymentStatus }) {
  return <Badge variant={PAY[status]}>{PAYMENT_STATUS_LABELS[status]}</Badge>
}
