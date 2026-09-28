import type { BountySummary, Me, PublicConfig } from '@/lib/api/types'

/** Test-only fixtures shaped exactly like docs/api.md responses. */
export function makeMe(overrides: Partial<Me> = {}): Me {
  return {
    id: 'u_1',
    email: 'ada@example.com',
    email_verified: true,
    username: 'ada',
    display_name: 'Ada Lovelace',
    avatar_url: null,
    bio: null,
    role: 'USER',
    skills: ['rust'],
    interests: [],
    github_url: null,
    portfolio_url: null,
    wants_to_request: true,
    wants_to_contribute: true,
    onboarding: {
      email_verified: true,
      profile_completed: true,
      role_selected: true,
      wallet_connected: true,
      first_action_taken: true,
      completed: true,
    },
    permissions: ['bounty:create'],
    created_at: '2026-09-01T12:00:00Z',
    ...overrides,
  }
}

export function makeBounty(overrides: Partial<BountySummary> = {}): BountySummary {
  return {
    id: 'b_1',
    slug: 'add-soroban-indexer',
    title: 'Add a Soroban event indexer',
    short_description: 'Index escrow contract events into Postgres for the payouts dashboard.',
    category: 'DEVELOPMENT',
    difficulty: 'ADVANCED',
    tags: ['backend'],
    required_skills: ['rust', 'soroban', 'postgres'],
    reward_amount: '1250.5000000',
    reward_asset: { code: 'XLM', issuer: null, type: 'native', contract_id: null },
    total_reward: '2501.0000000',
    network: 'testnet',
    status: 'FUNDED',
    funding_status: 'FUNDED',
    application_deadline: '2099-01-01T00:00:00Z',
    completion_deadline: null,
    positions_available: 2,
    positions_filled: 0,
    applications_count: 3,
    requester: { id: 'u_2', username: 'grace', display_name: 'Grace Hopper', avatar_url: null },
    is_featured: false,
    is_bookmarked: false,
    created_at: '2026-09-20T12:00:00Z',
    published_at: '2026-09-20T12:00:00Z',
    ...overrides,
  }
}

export function makeConfig(overrides: Partial<PublicConfig> = {}): PublicConfig {
  return {
    app_name: 'BountyFlow',
    network: 'testnet',
    network_passphrase: 'Test SDF Network ; September 2015',
    horizon_url: 'https://horizon-testnet.stellar.org',
    soroban_rpc_url: 'https://soroban-testnet.stellar.org',
    explorer_base_url: 'https://stellar.expert/explorer/testnet',
    contract_id: 'CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC',
    native_asset_contract_id: null,
    arbiter_address: null,
    blockchain_mode: 'testnet',
    ...overrides,
  }
}

export function jsonResponse(
  body: unknown,
  init: { status?: number; headers?: Record<string, string> } = {},
) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'Content-Type': 'application/json', ...init.headers },
  })
}
