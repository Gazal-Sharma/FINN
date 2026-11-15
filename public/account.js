// Optional sign-in. Everything works without it; signing in only syncs your
// preferences (stocks you follow, alert thresholds, appearance, voice) across devices.
// Sign-in is a 6-digit code sent by email (more reliable on phones than a magic link).
import { SUPABASE_URL, SUPABASE_ANON_KEY } from "./config.js";

export const enabled = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);
let client = null;
let user = null;
let onChange = () => {};
let saveTimer = null;

async function sb() {
  if (!enabled) return null;
  if (!client) {
    const { createClient } = await import("https://esm.sh/@supabase/supabase-js@2");
    client = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, { auth: { persistSession: true, autoRefreshToken: true } });
  }
  return client;
}

export function currentUser() { return user; }

// Call once at boot. `getLocal()` returns the device's prefs, `applyRemote(p)` applies synced ones.
export async function init({ getLocal, applyRemote, changed }) {
  onChange = changed || onChange;
  const c = await sb();
  if (!c) return;
  const { data } = await c.auth.getSession();
  user = data.session?.user || null;
  if (user) await pull(getLocal, applyRemote);
  c.auth.onAuthStateChange(async (_e, session) => {
    const was = user?.id;
    user = session?.user || null;
    if (user && user.id !== was) await pull(getLocal, applyRemote);
    onChange();
  });
  onChange();
}

async function pull(getLocal, applyRemote) {
  const c = await sb();
  const { data, error } = await c.from("user_prefs").select("followed, settings").eq("user_id", user.id).maybeSingle();
  if (error) { console.warn("prefs load failed", error.message); return; }
  if (data) applyRemote({ followed: data.followed, ...data.settings });
  else await push(getLocal());  // first sign-in: this device's settings become the account's
}

async function push(prefs) {
  const c = await sb();
  if (!c || !user) return;
  const { followed = [], ...settings } = prefs;
  const { error } = await c.from("user_prefs").upsert({ user_id: user.id, followed, settings, updated_at: new Date().toISOString() });
  if (error) console.warn("prefs save failed", error.message);
}

// Debounced: sliders fire many changes in a row.
export function save(prefs) {
  if (!user) return;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => push(prefs), 800);
}

export async function sendCode(email) {
  const c = await sb();
  const { error } = await c.auth.signInWithOtp({ email, options: { shouldCreateUser: true } });
  if (error) throw new Error(error.message);
}

export async function verifyCode(email, token) {
  const c = await sb();
  const { error } = await c.auth.verifyOtp({ email, token, type: "email" });
  if (error) throw new Error(error.message);
}

export async function signOut() {
  const c = await sb();
  await c?.auth.signOut();
  user = null;
  onChange();
}
