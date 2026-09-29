import { readFile } from 'node:fs/promises'

import { apiCall, expect, newUser, registerViaApi, signIn, test, uniqueSuffix } from './fixtures'
import { REQUESTER } from './support/accounts'
import { EXPLORER_TX } from './support/chain-ui'
import {
  acceptViaApi,
  applyViaApi,
  chainActionViaApi,
  fundedBountyViaApi,
  linkWalletViaApi,
  newSession,
} from './support/flows'
import { installTestWallet } from './support/wallet'

/**
 * On-chain completion attestations and verifiable credentials, on Stellar Testnet.
 *
 * A real payout is made through the API with the lifecycle helpers (that flow is covered by the lifecycle
 * journey); what is under test here is what follows it: the worker attests the completion in the registry
 * contract, the attestation appears on both profiles with a valid explorer transaction, the contributor
 * downloads a credential, and the public verify page accepts it and rejects a tampered copy.
 *
 * Requires the worker to be running (it signs and submits the attestation) with STELLAR_ATTESTER_SECRET,
 * ATTESTATION_CONTRACT_ID and CREDENTIAL_ISSUER_SECRET configured.
 */

type Attestation = {
  id: string
  onchain_id: number | null
  status: string
  amount: string
  attestation_tx_hash: string | null
  attestation_explorer_url: string | null
}

const ATTESTED = 120_000

test('13. a verified payout is attested on-chain, and its credential verifies', async ({
  page,
  browser,
  guard,
}, testInfo) => {
  test.setTimeout(900_000)
  const requester = page
  const title = `E2E attestation bounty ${uniqueSuffix()}`

  // Setup (not under test): a funded bounty, an accepted contributor, an approved submission, a real payout.
  const requesterWallet = await installTestWallet(requester)
  await signIn(requester, REQUESTER)
  await linkWalletViaApi(requester, requesterWallet)
  const bounty = await fundedBountyViaApi(requester, requesterWallet, { title, reward_amount: '2' })

  const { page: contributorPage, wallet: contributorWallet } = await newSession(
    browser,
    testInfo,
    guard,
    'contributor',
  )
  const contributor = await registerViaApi(contributorPage, newUser('attest'))
  await linkWalletViaApi(contributorPage, contributorWallet!)
  const application = await applyViaApi(contributorPage, bounty.id)
  await acceptViaApi(requester, application.id)
  const submission = await apiCall<{ id: string }>(
    contributorPage,
    'POST',
    `/bounties/${bounty.id}/submissions`,
    { description: 'Delivered the work described in the acceptance criteria. (E2E setup)' },
  )
  await apiCall(requester, 'POST', `/submissions/${submission.id}/approve`, { feedback: 'Looks good' })
  const payout = await chainActionViaApi(
    requester,
    bounty.id,
    { action: 'PAYOUT', submission_id: submission.id },
    requesterWallet,
  )

  let attestation: Attestation | undefined

  await test.step('the worker records the completion in the attestation registry', async () => {
    await expect
      .poll(
        async () => {
          const page1 = await apiCall<{ items: Attestation[] }>(
            contributorPage,
            'GET',
            '/reputation/me/attestations',
          )
          attestation = page1.items[0]
          return attestation?.status ?? 'none'
        },
        {
          message: 'the completion is attested on-chain',
          timeout: ATTESTED,
          intervals: [2000, 3000, 5000],
        },
      )
      .toBe('CONFIRMED')
    expect(attestation!.onchain_id).toBeGreaterThan(0)
    expect(attestation!.amount).toBe('2.0000000')
    expect(attestation!.attestation_explorer_url).toMatch(EXPLORER_TX)
  })

  await test.step('the public profile shows it with its explorer links', async () => {
    const anon = await browser.newContext({ baseURL: testInfo.project.use.baseURL, colorScheme: 'light' })
    const visitor = await anon.newPage()
    guard.watch(visitor, 'visitor')
    await visitor.goto(`/u/${contributor.username}`)
    await visitor.getByRole('tab', { name: 'Completed on-chain' }).click()
    const row = visitor.getByRole('listitem').filter({ hasText: title })
    await expect(row).toHaveCount(1)
    await expect(row.getByText('Completed on-chain')).toBeVisible()
    await expect(row.getByText('2 XLM')).toBeVisible()
    await expect(row.getByRole('link', { name: `Attestation #${attestation!.onchain_id}` })).toBeVisible()
    await expect(
      row.getByRole('link', { name: /view attestation transaction hash on stellar explorer/i }),
    ).toHaveAttribute('href', EXPLORER_TX)
    await expect(
      visitor.getByRole('region', { name: 'Profile details' }).getByText('Completed on-chain'),
    ).toBeVisible()

    await test.step('the public attestation page reads the record back from the contract', async () => {
      await row.getByRole('link', { name: `Attestation #${attestation!.onchain_id}` }).click()
      await expect(visitor).toHaveURL(new RegExp(`/attestations/${attestation!.onchain_id}$`))
      await expect(visitor.getByRole('heading', { level: 1, name: title })).toBeVisible()
      await expect(visitor.getByText('Matches the payout')).toBeVisible({ timeout: 30_000 })
      await expect(
        visitor.getByRole('link', { name: /view payout transaction hash on stellar explorer/i }).first(),
      ).toHaveAttribute('href', `https://stellar.expert/explorer/testnet/tx/${payout.transaction_hash}`)
    })
    await anon.close()
  })

  let credential = ''

  await test.step('the contributor downloads a credential from their profile', async () => {
    await contributorPage.goto('/app/profile')
    const section = contributorPage.getByRole('region', { name: 'Completed on-chain' })
    await expect(section.getByText(title)).toBeVisible()
    const download = contributorPage.waitForEvent('download')
    await section.getByRole('button', { name: `Download credential for ${title}` }).click()
    const file = await download
    expect(file.suggestedFilename()).toMatch(/^bountyflow-completion-credential-[0-9a-f]{8}\.json$/)
    credential = await readFile(await file.path(), 'utf8')
    const parsed = JSON.parse(credential) as {
      type: string[]
      proof: { cryptosuite: string }
      credentialSubject: { completion: { attestation: { id: number } } }
    }
    expect(parsed.type).toContain('BountyCompletionCredential')
    expect(parsed.proof.cryptosuite).toBe('eddsa-jcs-2022')
    expect(parsed.credentialSubject.completion.attestation.id).toBe(attestation!.onchain_id)
  })

  await test.step('anyone can verify it on the public page', async () => {
    const anon = await browser.newContext({ baseURL: testInfo.project.use.baseURL, colorScheme: 'light' })
    const visitor = await anon.newPage()
    guard.watch(visitor, 'verifier')
    await visitor.goto('/credentials/verify')
    await visitor.getByLabel('Credential JSON').fill(credential)
    await visitor.getByRole('button', { name: 'Verify' }).click()
    await expect(visitor.getByRole('heading', { name: 'Credential verified' })).toBeVisible({
      timeout: 60_000,
    })
    const checks = visitor.getByRole('list', { name: 'Verification checks' })
    for (const label of [
      'Credential format',
      'Issuer',
      'Signature',
      'Validity period',
      'Revocation status',
      'On-chain attestation',
    ]) {
      await expect(checks.getByRole('listitem').filter({ hasText: label })).toContainText('passed')
    }
    await expect(visitor.getByRole('link', { name: `Attestation #${attestation!.onchain_id}` })).toBeVisible()

    await test.step('a tampered credential fails', async () => {
      const tampered = JSON.parse(credential) as {
        credentialSubject: { completion: { amount: string } }
      }
      tampered.credentialSubject.completion.amount = '2000.0000000'
      await visitor.getByRole('button', { name: 'Clear' }).click()
      await visitor.getByLabel('Credential JSON').fill(JSON.stringify(tampered))
      await visitor.getByRole('button', { name: 'Verify' }).click()
      await expect(visitor.getByRole('heading', { name: 'Credential not verified' })).toBeVisible({
        timeout: 60_000,
      })
      await expect(checks.getByRole('listitem').filter({ hasText: 'Signature' })).toContainText('fail')
    })
    await anon.close()
  })
})
