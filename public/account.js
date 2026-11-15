// Optional sign-in. Everything works without it; signing in only syncs your
// preferences (stocks you follow, alert thresholds, appearance, voice) across devices.
// Sign-in is Supabase's default email magic link: the link returns to this same
// site (live or branch preview), where the session is picked up from the URL.
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
    // implicit flow: the link carries the session itself, so it still works if the
    // email app opens it in a different browser tab than the one that asked for it
    client = createClient(SUPABASE_URL, SUPABASE_ANON_KEY,
      { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true, flowType: "implicit" } });
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

export async function sendLink(email) {
  const c = await sb();
  const back = location.origin + location.pathname;  // return to whichever site you're on
  const { error } = await c.auth.signInWithOtp({ email, options: { shouldCreateUser: true, emailRedirectTo: back } });
  if (error) throw new Error(error.message);
}

export async function signOut() {
  const c = await sb();
  await c?.auth.signOut();
  user = null;
  onChange();
}
