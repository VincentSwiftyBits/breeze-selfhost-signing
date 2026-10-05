import { useCallback, useEffect, useState } from 'react';
import { Activity, Building2, Handshake, Plus, RefreshCw, X } from 'lucide-react';
import { fetchWithAuth } from '../../stores/auth';
import { useJwtClaims } from '../../lib/authScope';
import AccessDenied from '../shared/AccessDenied';
import { showToast } from '../shared/Toast';

type Connection = {
  id: string;
  organizationName: string;
  displayName: string;
  status: 'healthy' | 'degraded' | 'critical' | 'stale' | 'auth_required' | 'paused' | 'unsupported';
  lastError: string | null;
  latestSnapshot?: { extensionCount?: number; activeExtensionCount?: number } | null;
};
type Organization = { id: string; name: string };
type CreatedConnection = { webhookUrl: string; webhookVerificationToken: string };

const statusStyles: Record<Connection['status'], string> = {
  healthy: 'bg-green-500/10 text-green-700 dark:text-green-400',
  degraded: 'bg-amber-500/10 text-amber-700 dark:text-amber-400',
  critical: 'bg-red-500/10 text-red-700 dark:text-red-400',
  stale: 'bg-orange-500/10 text-orange-700 dark:text-orange-400',
  auth_required: 'bg-blue-500/10 text-blue-700 dark:text-blue-400',
  paused: 'bg-muted text-muted-foreground',
  unsupported: 'bg-muted text-muted-foreground',
};

export default function VendorsSuppliersPage() {
  const claimsState = useJwtClaims();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [loading, setLoading] = useState(true);
  const [showConnect, setShowConnect] = useState(false);
  const [saving, setSaving] = useState(false);
  const [createdConnection, setCreatedConnection] = useState<CreatedConnection | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [hubResponse, orgResponse] = await Promise.all([
        fetchWithAuth('/vendor-hub/dashboard', { skipOrgIdInjection: true }),
        fetchWithAuth('/orgs', { skipOrgIdInjection: true }),
      ]);
      if (!hubResponse.ok) throw new Error(`Vendor Hub returned ${hubResponse.status}`);
      const hub = await hubResponse.json() as { connections?: Connection[] };
      const orgs = orgResponse.ok ? await orgResponse.json() as { organizations?: Organization[]; data?: Organization[] } : {};
      setConnections(hub.connections ?? []);
      setOrganizations(orgs.organizations ?? orgs.data ?? []);
    } catch (error) {
      showToast({ type: 'error', message: `Vendor Hub unavailable: ${error instanceof Error ? error.message : 'Unable to load vendor connections.'}` });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (claimsState.status === 'resolved' && claimsState.claims.scope !== 'partner') {
    return <AccessDenied message="Vendors & Suppliers is available only to internal partner technicians." />;
  }

  async function connectRingCentral(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    const form = new FormData(event.currentTarget);
    const breezeOrgId = String(form.get('breezeOrgId') ?? '');
    const organization = organizations.find((item) => item.id === breezeOrgId);
    try {
      const response = await fetchWithAuth('/vendor-hub/ringcentral/connections', {
        method: 'POST', skipOrgIdInjection: true, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          breezeOrgId,
          organizationName: organization?.name ?? '',
          displayName: form.get('displayName'),
          clientId: form.get('clientId'),
          clientSecret: form.get('clientSecret'),
          jwt: form.get('jwt'),
        }),
      });
      const body = await response.json().catch(() => ({})) as { error?: string; webhookUrl?: string; webhookVerificationToken?: string };
      if (!response.ok) throw new Error(body.error ?? `Connection failed (${response.status})`);
      if (!body.webhookUrl || !body.webhookVerificationToken) throw new Error('Vendor Hub did not return RingCentral webhook setup details.');
      showToast({ type: 'success', message: 'RingCentral connected. Credentials were encrypted; run the first synchronization to validate access.' });
      setShowConnect(false);
      setCreatedConnection({ webhookUrl: body.webhookUrl, webhookVerificationToken: body.webhookVerificationToken });
      await load();
    } catch (error) {
      showToast({ type: 'error', message: `Could not connect RingCentral: ${error instanceof Error ? error.message : 'Connection failed.'}` });
    } finally {
      setSaving(false);
    }
  }

  async function sync(connection: Connection) {
    const response = await fetchWithAuth(`/vendor-hub/connections/${connection.id}/sync`, { method: 'POST', skipOrgIdInjection: true });
    const body = await response.json().catch(() => ({})) as { error?: string };
    if (!response.ok) {
      showToast({ type: 'error', message: `Synchronization failed: ${body.error ?? `Vendor Hub returned ${response.status}`}` });
      return;
    }
    showToast({ type: 'success', message: `Synchronization complete: ${connection.displayName} has been refreshed.` });
    await load();
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6" data-testid="vendors-suppliers-page">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3"><Handshake className="h-7 w-7 text-primary" /><h1 className="text-2xl font-semibold">Vendors &amp; Suppliers</h1></div>
          <p className="mt-2 text-sm text-muted-foreground">Monitor customer vendor services without modifying Breeze business data.</p>
        </div>
        <button className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground" onClick={() => setShowConnect(true)}><Plus className="h-4 w-4" /> Add RingCentral</button>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Summary label="Connected accounts" value={connections.length} icon={Building2} />
        <Summary label="Healthy" value={connections.filter((item) => item.status === 'healthy').length} icon={Activity} />
        <Summary label="Needs attention" value={connections.filter((item) => ['critical', 'degraded', 'auth_required', 'stale'].includes(item.status)).length} icon={RefreshCw} />
      </div>

      <div className="overflow-hidden rounded-lg border bg-card">
        <div className="border-b px-5 py-4"><h2 className="font-medium">RingCentral customer accounts</h2></div>
        {loading ? <div className="p-8 text-center text-sm text-muted-foreground">Loading vendor connections…</div> : connections.length === 0 ? (
          <div className="p-10 text-center"><p className="font-medium">No vendor accounts connected</p><p className="mt-1 text-sm text-muted-foreground">Start with the HCTB RingCentral account.</p></div>
        ) : <div className="divide-y">{connections.map((connection) => (
          <div className="grid gap-4 p-5 md:grid-cols-[1.2fr_1fr_1fr_auto] md:items-center" key={connection.id}>
            <div><p className="font-medium">{connection.organizationName}</p><p className="text-sm text-muted-foreground">{connection.displayName}</p></div>
            <div><span className={`rounded-full px-2.5 py-1 text-xs font-medium ${statusStyles[connection.status]}`}>{connection.status.replace('_', ' ')}</span></div>
            <div className="text-sm text-muted-foreground">{connection.latestSnapshot ? `${connection.latestSnapshot.activeExtensionCount ?? 0}/${connection.latestSnapshot.extensionCount ?? 0} active extensions` : 'Not synchronized'}</div>
            <button className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm" onClick={() => void sync(connection)}><RefreshCw className="h-4 w-4" /> Sync</button>
            {connection.lastError && <p className="text-sm text-destructive md:col-span-4">{connection.lastError}</p>}
          </div>
        ))}</div>}
      </div>

      {showConnect && <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4">
        <form className="w-full max-w-xl space-y-4 rounded-lg border bg-background p-6 shadow-xl" onSubmit={connectRingCentral}>
          <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Connect RingCentral</h2><button type="button" onClick={() => setShowConnect(false)}><X className="h-5 w-5" /></button></div>
          <p className="text-sm text-muted-foreground">Use a dedicated read-only RingCentral app and JWT credential. Secrets are encrypted in Vendor Hub and are never stored in Breeze.</p>
          <Field label="Breeze organization"><select name="breezeOrgId" required className="w-full rounded-md border bg-background px-3 py-2"><option value="">Select a customer</option>{organizations.map((org) => <option key={org.id} value={org.id}>{org.name}</option>)}</select></Field>
          <Field label="Connection name"><input name="displayName" required placeholder="HCTB RingCentral" className="w-full rounded-md border bg-background px-3 py-2" /></Field>
          <Field label="Client ID"><input name="clientId" required autoComplete="off" className="w-full rounded-md border bg-background px-3 py-2" /></Field>
          <Field label="Client secret"><input name="clientSecret" type="password" required autoComplete="new-password" className="w-full rounded-md border bg-background px-3 py-2" /></Field>
          <Field label="JWT credential"><textarea name="jwt" required rows={4} className="w-full rounded-md border bg-background px-3 py-2 font-mono text-xs" /></Field>
          <div className="flex justify-end gap-3"><button type="button" className="rounded-md border px-4 py-2 text-sm" onClick={() => setShowConnect(false)}>Cancel</button><button disabled={saving} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50">{saving ? 'Saving…' : 'Connect'}</button></div>
        </form>
      </div>}

      {createdConnection && <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4">
        <div className="w-full max-w-xl space-y-4 rounded-lg border bg-background p-6 shadow-xl">
          <div><h2 className="text-lg font-semibold">Finish RingCentral webhook setup</h2><p className="mt-1 text-sm text-muted-foreground">Copy both values now. The verification token will not be shown again.</p></div>
          <Field label="Webhook URL"><input readOnly value={createdConnection.webhookUrl} onFocus={(event) => event.currentTarget.select()} className="w-full rounded-md border bg-muted px-3 py-2 font-mono text-xs" /></Field>
          <Field label="Verification token"><input readOnly value={createdConnection.webhookVerificationToken} onFocus={(event) => event.currentTarget.select()} className="w-full rounded-md border bg-muted px-3 py-2 font-mono text-xs" /></Field>
          <p className="text-sm text-muted-foreground">Create the RingCentral webhook subscription with this URL and set the same verification token in RingCentral. Vendor Hub will validate it on every event.</p>
          <div className="flex justify-end"><button className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground" onClick={() => setCreatedConnection(null)}>I saved both values</button></div>
        </div>
      </div>}
    </div>
  );
}

function Summary({ label, value, icon: Icon }: { label: string; value: number; icon: typeof Activity }) {
  return <div className="rounded-lg border bg-card p-5"><div className="flex items-center justify-between"><p className="text-sm text-muted-foreground">{label}</p><Icon className="h-4 w-4 text-muted-foreground" /></div><p className="mt-2 text-2xl font-semibold">{value}</p></div>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block space-y-1.5"><span className="text-sm font-medium">{label}</span>{children}</label>;
}
