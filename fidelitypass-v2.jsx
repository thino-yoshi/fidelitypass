import { useState, useEffect, useRef, useCallback } from "react";

// ─── CONFIG API ──────────────────────────────────────────────────────────────
const API_URL = "http://127.0.0.1:8000";

async function apiFetch(path, options = {}, token = null) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Erreur API");
  return data;
}

// ─── COULEURS PAR CATÉGORIE ──────────────────────────────────────────────────
const CATEGORY_STYLE = {
  "Café":        { emoji: "☕", color: "#C8822A", bg: "#FDF6EE" },
  "Boulangerie": { emoji: "🥐", color: "#D4A017", bg: "#FEFAED" },
  "Restaurant":  { emoji: "🍽️", color: "#C0392B", bg: "#FEF0EE" },
  "Healthy":     { emoji: "🥗", color: "#27AE60", bg: "#EDFEF4" },
  "Librairie":   { emoji: "📚", color: "#8E44AD", bg: "#F5EEFF" },
  "Coiffeur":    { emoji: "✂️", color: "#2980B9", bg: "#EEF6FF" },
  "default":     { emoji: "🏪", color: "#555", bg: "#F5F5F5" },
};
function getStyle(category) {
  return CATEGORY_STYLE[category] || CATEGORY_STYLE["default"];
}

// ─── ANIMATIONS CSS ──────────────────────────────────────────────────────────
const GLOBAL_CSS = `
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500;600;700&display=swap');
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --gold: #C8822A; --dark: #0F0E17; --dark2: #1A1828;
    --surface: #F7F5F2; --text: #1A1828; --muted: #6B6880;
    --green: #2ECC71; --red: #E74C3C; --radius: 16px;
  }
  body { font-family: 'DM Sans', sans-serif; background: var(--surface); color: var(--text); }
  @keyframes fadeUp   { from { opacity:0; transform:translateY(20px); } to { opacity:1; transform:none; } }
  @keyframes fadeIn   { from { opacity:0; } to { opacity:1; } }
  @keyframes spin     { to { transform:rotate(360deg); } }
  @keyframes pulse    { 0%,100% { transform:scale(1); } 50% { transform:scale(1.05); } }
  @keyframes scanLine { 0% { top:10%; } 100% { top:90%; } }
  @keyframes slideUp  { from { transform:translateY(100%); opacity:0; } to { transform:none; opacity:1; } }
  @keyframes confetti {
    0%   { transform: translateY(-20px) rotate(0deg); opacity:1; }
    100% { transform: translateY(300px) rotate(720deg); opacity:0; }
  }
  button { cursor:pointer; border:none; outline:none; font-family:inherit; }
  button:active { transform:scale(0.97); }
  ::-webkit-scrollbar { width:6px; }
  ::-webkit-scrollbar-thumb { background:#ccc; border-radius:3px; }
  input, textarea { font-family: inherit; }
`;

// ─── QR CODE SVG ─────────────────────────────────────────────────────────────
function generateQRPattern(seed) {
  const size = 21;
  let s = seed.split("").reduce((a, c) => a + c.charCodeAt(0), 0);
  const rand = () => { s = (s * 1664525 + 1013904223) & 0xffffffff; return (s >>> 0) / 0xffffffff; };
  const fixed = new Set();
  for (let r = 0; r < 7; r++) for (let c = 0; c < 7; c++) fixed.add(`${r},${c}`);
  for (let r = 0; r < 7; r++) for (let c = size-7; c < size; c++) fixed.add(`${r},${c}`);
  for (let r = size-7; r < size; r++) for (let c = 0; c < 7; c++) fixed.add(`${r},${c}`);
  const cells = [];
  for (let r = 0; r < size; r++) {
    for (let c = 0; c < size; c++) {
      const key = `${r},${c}`;
      if (fixed.has(key)) {
        const fr = r < 7 ? r : r-(size-7), fc = c < 7 ? c : c-(size-7);
        cells.push({ r, c, on: fr===0||fr===6||fc===0||fc===6||(fr>=2&&fr<=4&&fc>=2&&fc<=4) });
      } else {
        cells.push({ r, c, on: rand() > 0.5 });
      }
    }
  }
  return cells;
}
function QRCode({ value, size = 160, color = "#1a1a2e" }) {
  const cells = generateQRPattern(value);
  const cs = size / 21;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ display:"block" }}>
      <rect width={size} height={size} fill="white" rx="4" />
      {cells.filter(c => c.on).map(({ r, c }) => (
        <rect key={`${r},${c}`} x={c*cs} y={r*cs} width={cs} height={cs} fill={color} rx="0.5" />
      ))}
    </svg>
  );
}

// ─── CONFETTI ────────────────────────────────────────────────────────────────
function Confetti({ active }) {
  if (!active) return null;
  const pieces = Array.from({ length: 24 }, (_, i) => ({
    id: i,
    color: ["#C8822A","#F5C842","#2ECC71","#3498DB","#E74C3C","#9B59B6"][i % 6],
    left: `${Math.random()*100}%`,
    delay: `${Math.random()*0.5}s`,
    duration: `${0.8+Math.random()*0.8}s`,
    size: `${6+Math.random()*8}px`,
  }));
  return (
    <div style={{ position:"fixed", inset:0, pointerEvents:"none", zIndex:9999, overflow:"hidden" }}>
      {pieces.map(p => (
        <div key={p.id} style={{
          position:"absolute", top:"-20px", left:p.left,
          width:p.size, height:p.size, background:p.color, borderRadius:"2px",
          animation:`confetti ${p.duration} ${p.delay} ease-in forwards`,
        }} />
      ))}
    </div>
  );
}

// ─── TOAST ───────────────────────────────────────────────────────────────────
function Toast({ toast, onClose }) {
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(onClose, 3500);
    return () => clearTimeout(t);
  }, [toast]);
  if (!toast) return null;
  const colors = { success:"#2ECC71", error:"#E74C3C", info:"#3498DB" };
  const icons  = { success:"✓", error:"✗", info:"ℹ" };
  return (
    <div style={{
      position:"fixed", bottom:24, right:24, zIndex:10000,
      background:"white", borderRadius:12, padding:"14px 18px",
      boxShadow:"0 8px 32px rgba(0,0,0,0.18)", display:"flex", alignItems:"center", gap:12,
      animation:"fadeIn 0.3s ease", maxWidth:340, border:`2px solid ${colors[toast.type]}22`,
    }}>
      <div style={{
        width:32, height:32, borderRadius:"50%", background:colors[toast.type],
        display:"flex", alignItems:"center", justifyContent:"center",
        color:"white", fontWeight:700, fontSize:16, flexShrink:0,
      }}>{icons[toast.type]}</div>
      <div>
        <div style={{ fontWeight:600, fontSize:14 }}>{toast.title}</div>
        {toast.msg && <div style={{ fontSize:13, color:"#6B6880", marginTop:2 }}>{toast.msg}</div>}
      </div>
      <button onClick={onClose} style={{ background:"none", fontSize:18, color:"#aaa", marginLeft:"auto", padding:"0 4px" }}>×</button>
    </div>
  );
}

// ─── SPINNER ─────────────────────────────────────────────────────────────────
function Spinner({ color = "#C8822A", size = 40 }) {
  return (
    <div style={{
      width:size, height:size, border:`3px solid ${color}33`,
      borderTopColor:color, borderRadius:"50%", animation:"spin 0.8s linear infinite",
    }} />
  );
}

// ════════════════════════════════════════════════════════════
//  ÉCRAN DE LOGIN / REGISTER
// ════════════════════════════════════════════════════════════
function AuthScreen({ onAuth }) {
  const [mode, setMode]       = useState("login");
  const [userType, setUserType] = useState("client");
  const [name, setName]       = useState("");
  const [email, setEmail]     = useState("");
  const [pass, setPass]       = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState("");

  const inputStyle = {
    width:"100%", padding:"13px 16px", borderRadius:12,
    border:"1.5px solid #eee", fontSize:14, outline:"none",
    background:"#fafafa", boxSizing:"border-box",
  };

  const submit = async () => {
    setError(""); setLoading(true);
    try {
      let data;
      if (mode === "register") {
        data = await apiFetch("/auth/register", {
          method:"POST",
          body: JSON.stringify({ email, password:pass, name, user_type:userType }),
        });
      } else {
        data = await apiFetch("/auth/login", {
          method:"POST",
          body: JSON.stringify({ email, password:pass }),
        });
      }
      onAuth(data.token, data.user_type, data.name);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight:"100vh", background:"linear-gradient(160deg,#0F0E17,#1A1828)", display:"flex", alignItems:"center", justifyContent:"center", padding:20 }}>
      <div style={{ width:"100%", maxWidth:400, background:"white", borderRadius:24, overflow:"hidden", boxShadow:"0 32px 80px rgba(0,0,0,0.4)" }}>
        {/* Header */}
        <div style={{ background:"linear-gradient(135deg,#C8822A,#E09A42)", padding:"36px 28px 28px", textAlign:"center" }}>
          <div style={{ fontSize:48, marginBottom:8 }}>🎯</div>
          <h1 style={{ fontFamily:"DM Serif Display, serif", fontSize:28, color:"white", marginBottom:4 }}>FidelityPass</h1>
          <p style={{ color:"rgba(255,255,255,0.75)", fontSize:13 }}>
            {mode === "login" ? "Content de te revoir !" : "Rejoins la plateforme"}
          </p>
        </div>

        <div style={{ padding:"24px 28px 32px" }}>
          {/* Toggle login/register */}
          <div style={{ display:"flex", background:"#f5f5f5", borderRadius:12, padding:4, marginBottom:20 }}>
            {["login","register"].map(m => (
              <button key={m} onClick={() => setMode(m)} style={{
                flex:1, padding:"10px 0", border:"none", borderRadius:9,
                background:mode===m?"white":"transparent",
                fontWeight:700, fontSize:14, color:mode===m?"#C8822A":"#888",
                boxShadow:mode===m?"0 2px 8px rgba(0,0,0,0.08)":"none", transition:"all 0.2s",
              }}>{m==="login"?"Connexion":"Inscription"}</button>
            ))}
          </div>

          {/* Type utilisateur (register uniquement) */}
          {mode === "register" && (
            <div style={{ display:"flex", gap:10, marginBottom:16 }}>
              {[{v:"client",icon:"👤",label:"Client"},{v:"merchant",icon:"🏪",label:"Commerçant"}].map(t => (
                <button key={t.v} onClick={() => setUserType(t.v)} style={{
                  flex:1, padding:"12px 8px", borderRadius:12,
                  border:`2px solid ${userType===t.v?"#C8822A":"#eee"}`,
                  background:userType===t.v?"#FDF6EE":"white",
                  color:userType===t.v?"#C8822A":"#888", fontWeight:700, fontSize:13,
                  display:"flex", alignItems:"center", justifyContent:"center", gap:6, transition:"all 0.2s",
                }}><span>{t.icon}</span>{t.label}</button>
              ))}
            </div>
          )}

          <div style={{ display:"flex", flexDirection:"column", gap:12 }}>
            {mode==="register" && (
              <input value={name} onChange={e=>setName(e.target.value)}
                placeholder="Nom complet / Nom du commerce" style={inputStyle} />
            )}
            <input value={email} onChange={e=>setEmail(e.target.value)}
              placeholder="Email" type="email" style={inputStyle} />
            <input value={pass} onChange={e=>setPass(e.target.value)}
              placeholder="Mot de passe" type="password" style={inputStyle} />

            {error && (
              <div style={{ background:"#FEF0EE", border:"1px solid #E74C3C33", borderRadius:10, padding:"10px 14px", color:"#E74C3C", fontSize:13, fontWeight:600 }}>
                ✗ {error}
              </div>
            )}

            <button onClick={submit} disabled={loading} style={{
              padding:"14px", background:"linear-gradient(135deg,#C8822A,#E09A42)",
              color:"white", border:"none", borderRadius:12, fontSize:15, fontWeight:800,
              marginTop:4, opacity:loading?0.7:1, display:"flex", alignItems:"center", justifyContent:"center", gap:10,
            }}>
              {loading ? <Spinner color="white" size={22} /> : (mode==="login" ? "Se connecter" : "Créer mon compte")}
            </button>

            {/* Social */}
            <div style={{ display:"flex", alignItems:"center", gap:12 }}>
              <div style={{ flex:1, height:1, background:"#eee" }}/>
              <span style={{ fontSize:12, color:"#bbb" }}>ou</span>
              <div style={{ flex:1, height:1, background:"#eee" }}/>
            </div>
            <div style={{ display:"flex", gap:10 }}>
              {[{label:"Apple",icon:"🍎",bg:"#000",color:"white"},{label:"Google",icon:"G",bg:"white",color:"#444",border:"1.5px solid #eee"}].map(s => (
                <button key={s.label} style={{
                  flex:1, padding:"12px", background:s.bg, color:s.color,
                  border:s.border||"none", borderRadius:12, fontSize:14, fontWeight:700,
                  display:"flex", alignItems:"center", justifyContent:"center", gap:8,
                  opacity:0.5, cursor:"not-allowed",
                }} title="Bientôt disponible">
                  <span>{s.icon}</span> {s.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════
//  APP CLIENT
// ════════════════════════════════════════════════════════════
function ClientApp({ token, userName, onLogout }) {
  const [tab, setTab]           = useState("stores");
  const [merchants, setMerchants] = useState([]);
  const [myCards, setMyCards]   = useState([]);
  const [search, setSearch]     = useState("");
  const [selectedCard, setSelectedCard] = useState(null);
  const [createFor, setCreateFor] = useState(null);
  const [toast, setToast]       = useState(null);
  const [loading, setLoading]   = useState(true);
  const [qrSeed, setQrSeed]     = useState(() => Math.random().toString(36).slice(2));
  const [qrTime, setQrTime]     = useState(60);

  // Charger les données
  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [m, c] = await Promise.all([
          apiFetch("/merchants/", {}, token),
          apiFetch("/cards/me", {}, token),
        ]);
        setMerchants(m);
        setMyCards(c);
      } catch (e) {
        setToast({ type:"error", title:"Erreur de chargement", msg:e.message });
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [token]);

  // Timer QR
  useEffect(() => {
    if (!selectedCard) return;
    const interval = setInterval(() => {
      setQrTime(t => {
        if (t <= 1) { setQrSeed(Math.random().toString(36).slice(2)); return 60; }
        return t - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [selectedCard]);

  const createCard = async (merchant) => {
    if (myCards.find(c => c.merchant_id === merchant.id)) {
      setToast({ type:"info", title:"Carte déjà existante", msg:`Tu as déjà une carte chez ${merchant.business_name}` });
      setCreateFor(null); return;
    }
    try {
      const card = await apiFetch("/cards/", { method:"POST", body:JSON.stringify({ merchant_id:merchant.id }) }, token);
      setMyCards(prev => [...prev, card]);
      setCreateFor(null);
      setTab("cards");
      setToast({ type:"success", title:"Carte créée ! 🎉", msg:`Ta carte chez ${merchant.business_name} est prête` });
    } catch (e) {
      setToast({ type:"error", title:"Erreur", msg:e.message });
    }
  };

  const filtered = merchants.filter(m =>
    m.business_name.toLowerCase().includes(search.toLowerCase()) ||
    m.category.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div style={{ background:"#F7F5F2", minHeight:"100vh", maxWidth:480, margin:"0 auto" }}>
      <Toast toast={toast} onClose={() => setToast(null)} />

      {/* Header */}
      <div style={{ background:"linear-gradient(135deg,#0F0E17,#1A1828)", padding:"48px 24px 28px", position:"relative", overflow:"hidden" }}>
        <div style={{ position:"absolute", top:-40, right:-40, width:160, height:160, borderRadius:"50%", background:"rgba(200,130,42,0.08)" }} />
        <div style={{ position:"relative", display:"flex", alignItems:"center", justifyContent:"space-between" }}>
          <div>
            <div style={{ fontSize:13, color:"rgba(255,255,255,0.5)", marginBottom:4 }}>Bonjour,</div>
            <div style={{ fontSize:24, fontWeight:800, color:"white" }}>{userName} 👋</div>
            <div style={{ fontSize:13, color:"rgba(200,130,42,0.8)", marginTop:4 }}>{myCards.length} carte(s) active(s)</div>
          </div>
          <button onClick={onLogout} style={{
            background:"rgba(255,255,255,0.1)", color:"rgba(255,255,255,0.7)",
            border:"1px solid rgba(255,255,255,0.15)", borderRadius:10, padding:"8px 14px", fontSize:12, fontWeight:600,
          }}>Sortir</button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display:"flex", background:"white", borderBottom:"1px solid #f0f0f0", position:"sticky", top:0, zIndex:100 }}>
        {[{key:"stores",label:"Commerces",icon:"🏪"},{key:"cards",label:`Mes cartes (${myCards.length})`,icon:"💳"}].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)} style={{
            flex:1, padding:"14px 8px", border:"none", background:"transparent",
            fontSize:14, fontWeight:700, color:tab===t.key?"#C8822A":"#999",
            borderBottom:`3px solid ${tab===t.key?"#C8822A":"transparent"}`,
            transition:"all 0.2s", display:"flex", alignItems:"center", justifyContent:"center", gap:6,
          }}><span>{t.icon}</span>{t.label}</button>
        ))}
      </div>

      <div style={{ padding:"16px" }}>
        {loading ? (
          <div style={{ display:"flex", justifyContent:"center", padding:"60px 0" }}><Spinner /></div>
        ) : (
          <>
            {/* ── ONGLET COMMERCES ── */}
            {tab === "stores" && (
              <>
                <input value={search} onChange={e=>setSearch(e.target.value)}
                  placeholder="🔍  Rechercher un commerce..."
                  style={{
                    width:"100%", padding:"12px 16px", borderRadius:12,
                    border:"1.5px solid #eee", fontSize:14, outline:"none",
                    background:"white", boxSizing:"border-box", marginBottom:16,
                  }}
                />
                <p style={{ margin:"0 0 12px", fontSize:12, color:"#aaa", fontWeight:700, letterSpacing:1, textTransform:"uppercase" }}>
                  {filtered.length} commerces partenaires
                </p>
                <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
                  {filtered.length === 0 && (
                    <div style={{ textAlign:"center", padding:"40px 0", color:"#aaa" }}>Aucun commerce trouvé</div>
                  )}
                  {filtered.map(m => {
                    const style = getStyle(m.category);
                    const hasCard = myCards.find(c => c.merchant_id === m.id);
                    return (
                      <div key={m.id} style={{
                        background:"white", borderRadius:16, padding:"16px",
                        boxShadow:"0 2px 12px rgba(0,0,0,0.06)",
                        display:"flex", alignItems:"center", gap:14,
                        border:`1.5px solid ${createFor?.id===m.id ? style.color : "transparent"}`,
                      }}>
                        <div style={{ width:52, height:52, borderRadius:14, background:style.bg, display:"flex", alignItems:"center", justifyContent:"center", fontSize:26, flexShrink:0 }}>
                          {style.emoji}
                        </div>
                        <div style={{ flex:1 }}>
                          <div style={{ fontWeight:800, fontSize:15, color:"#1A1828" }}>{m.business_name}</div>
                          <div style={{ fontSize:12, color:"#aaa", marginTop:2 }}>{m.category}</div>
                          <div style={{ fontSize:11, color:style.color, fontWeight:700, marginTop:4 }}>
                            🎁 {m.reward_description} · {m.stamps_required} tampons
                          </div>
                        </div>
                        {hasCard ? (
                          <div style={{ padding:"6px 12px", background:"#eefff5", color:"#27AE60", borderRadius:99, fontSize:11, fontWeight:800 }}>✓ Active</div>
                        ) : (
                          <button onClick={() => setCreateFor(createFor?.id===m.id ? null : m)} style={{
                            padding:"8px 14px", background:style.color, color:"white",
                            border:"none", borderRadius:10, fontSize:12, fontWeight:800, flexShrink:0,
                          }}>+ Carte</button>
                        )}
                      </div>
                    );
                  })}
                </div>
              </>
            )}

            {/* ── ONGLET MES CARTES ── */}
            {tab === "cards" && (
              <>
                {myCards.length === 0 ? (
                  <div style={{ textAlign:"center", padding:"60px 20px" }}>
                    <div style={{ fontSize:48, marginBottom:16 }}>💳</div>
                    <p style={{ color:"#aaa", fontSize:15 }}>Pas encore de carte.<br/>Va dans Commerces pour en créer une !</p>
                  </div>
                ) : (
                  <div style={{ display:"flex", flexDirection:"column", gap:12 }}>
                    {myCards.map(card => {
                      const merchant = merchants.find(m => m.id === card.merchant_id);
                      if (!merchant) return null;
                      const style = getStyle(merchant.category);
                      const pct = Math.round((card.stamps_count / merchant.stamps_required) * 100);
                      return (
                        <div key={card.id} onClick={() => { setSelectedCard({...card, merchant, style}); setQrTime(60); }}
                          style={{
                            background:`linear-gradient(135deg, ${style.color}, ${style.color}cc)`,
                            borderRadius:20, padding:"20px", cursor:"pointer",
                            boxShadow:`0 4px 20px ${style.color}44`, position:"relative", overflow:"hidden",
                          }}>
                          <div style={{ position:"absolute", right:-20, top:-20, width:100, height:100, borderRadius:"50%", background:"rgba(255,255,255,0.1)" }} />
                          <div style={{ position:"relative", zIndex:1 }}>
                            <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start" }}>
                              <div>
                                <div style={{ fontSize:11, color:"rgba(255,255,255,0.7)", fontWeight:700, letterSpacing:1, textTransform:"uppercase" }}>Carte fidélité</div>
                                <div style={{ fontSize:20, fontWeight:900, color:"white", marginTop:2 }}>{merchant.business_name}</div>
                              </div>
                              <div style={{ fontSize:32 }}>{style.emoji}</div>
                            </div>
                            <div style={{ display:"flex", gap:6, margin:"14px 0 10px", flexWrap:"wrap" }}>
                              {Array.from({length:merchant.stamps_required}).map((_,i) => (
                                <div key={i} style={{
                                  width:26, height:26, borderRadius:"50%",
                                  background:i < card.stamps_count ? "white" : "rgba(255,255,255,0.25)",
                                  display:"flex", alignItems:"center", justifyContent:"center", fontSize:12,
                                }}>{i < card.stamps_count ? "★" : ""}</div>
                              ))}
                            </div>
                            <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center" }}>
                              <div style={{ fontSize:13, color:"rgba(255,255,255,0.75)" }}>
                                {card.stamps_count >= merchant.stamps_required ? "🎉 Récompense disponible !" : `${merchant.stamps_required - card.stamps_count} tampon(s) restant(s)`}
                              </div>
                              <div style={{ fontSize:18, fontWeight:900, color:"white" }}>{card.stamps_count}/{merchant.stamps_required}</div>
                            </div>
                            <div style={{ height:4, background:"rgba(255,255,255,0.2)", borderRadius:99, marginTop:8 }}>
                              <div style={{ width:`${pct}%`, height:4, background:"white", borderRadius:99, transition:"width 0.5s" }} />
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>

      {/* ── MODAL CRÉER CARTE ── */}
      {createFor && (() => {
        const style = getStyle(createFor.category);
        return (
          <div style={{ position:"fixed", inset:0, background:"rgba(0,0,0,0.5)", display:"flex", alignItems:"flex-end", zIndex:100 }} onClick={() => setCreateFor(null)}>
            <div onClick={e=>e.stopPropagation()} style={{ background:"white", borderRadius:"24px 24px 0 0", padding:"28px 24px 40px", width:"100%", animation:"slideUp 0.3s ease" }}>
              <div style={{ width:40, height:4, background:"#eee", borderRadius:99, margin:"0 auto 20px" }} />
              <div style={{ textAlign:"center", marginBottom:20 }}>
                <div style={{ fontSize:48 }}>{style.emoji}</div>
                <h3 style={{ margin:"8px 0 4px", fontSize:20, fontWeight:900, color:"#1A1828" }}>{createFor.business_name}</h3>
                <p style={{ margin:0, color:"#888", fontSize:14 }}>{createFor.category}</p>
                <div style={{ display:"inline-block", marginTop:8, padding:"6px 14px", background:style.bg, color:style.color, borderRadius:99, fontSize:13, fontWeight:700 }}>
                  🎁 {createFor.reward_description}
                </div>
              </div>
              <div style={{ background:"#fafafa", borderRadius:14, padding:"14px 16px", marginBottom:20, fontSize:14, color:"#555", lineHeight:1.6 }}>
                Collecte <strong style={{ color:style.color }}>{createFor.stamps_required} tampons</strong> pour obtenir ta récompense.<br/>Un QR code unique te sera attribué.
              </div>
              <button onClick={() => createCard(createFor)} style={{
                width:"100%", padding:"16px", background:style.color, color:"white",
                border:"none", borderRadius:14, fontSize:16, fontWeight:900,
                boxShadow:`0 4px 16px ${style.color}55`,
              }}>Créer ma carte de fidélité</button>
              <button onClick={() => setCreateFor(null)} style={{ width:"100%", padding:"12px", background:"transparent", color:"#aaa", border:"none", fontSize:14, marginTop:8, fontWeight:600 }}>Annuler</button>
            </div>
          </div>
        );
      })()}

      {/* ── MODAL QR CODE ── */}
      {selectedCard && (() => {
        const { merchant, style } = selectedCard;
        return (
          <div style={{ position:"fixed", inset:0, background:"rgba(0,0,0,0.6)", display:"flex", alignItems:"flex-end", zIndex:100 }} onClick={() => setSelectedCard(null)}>
            <div onClick={e=>e.stopPropagation()} style={{ background:"white", borderRadius:"24px 24px 0 0", padding:"24px 24px 40px", width:"100%", animation:"slideUp 0.3s ease" }}>
              <div style={{ width:40, height:4, background:"#eee", borderRadius:99, margin:"0 auto 20px" }} />
              <div style={{ display:"flex", alignItems:"center", gap:14, marginBottom:20 }}>
                <div style={{ width:52, height:52, borderRadius:14, background:style.bg, display:"flex", alignItems:"center", justifyContent:"center", fontSize:26 }}>{style.emoji}</div>
                <div>
                  <div style={{ fontWeight:900, fontSize:18, color:"#1A1828" }}>{merchant.business_name}</div>
                  <div style={{ fontSize:13, color:"#aaa" }}>{merchant.category}</div>
                </div>
              </div>
              <div style={{ display:"flex", justifyContent:"center", padding:"20px", background:"white", borderRadius:16, border:`2px solid ${style.color}33`, marginBottom:16, boxShadow:"0 4px 20px rgba(0,0,0,0.06)" }}>
                <QRCode value={selectedCard.qr_token || qrSeed} size={180} color={style.color} />
              </div>
              {/* Timer */}
              <div style={{ marginBottom:16 }}>
                <div style={{ display:"flex", justifyContent:"space-between", marginBottom:6 }}>
                  <span style={{ fontSize:12, color:"#6B6880" }}>🔒 QR sécurisé</span>
                  <span style={{ fontSize:13, fontWeight:700, color:qrTime < 15 ? "#E74C3C" : "#6B6880" }}>{qrTime}s</span>
                </div>
                <div style={{ background:"#f0f0f0", borderRadius:4, height:4, overflow:"hidden" }}>
                  <div style={{ height:"100%", background:qrTime < 15 ? "#E74C3C" : style.color, width:`${(qrTime/60)*100}%`, transition:"width 1s linear", borderRadius:4 }} />
                </div>
              </div>
              {/* Tampons */}
              <div style={{ background:"#fafafa", borderRadius:16, padding:"16px", marginBottom:16 }}>
                <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:12 }}>
                  <span style={{ fontWeight:800, fontSize:15, color:"#1A1828" }}>Mes tampons</span>
                  <span style={{ fontWeight:900, fontSize:18, color:style.color }}>{selectedCard.stamps_count}/{merchant.stamps_required}</span>
                </div>
                <div style={{ display:"flex", flexWrap:"wrap", gap:8, justifyContent:"center" }}>
                  {Array.from({length:merchant.stamps_required}).map((_,i) => (
                    <div key={i} style={{
                      width:36, height:36, borderRadius:"50%",
                      background:i < selectedCard.stamps_count ? style.color : "transparent",
                      border:`2.5px solid ${i < selectedCard.stamps_count ? style.color : "#ddd"}`,
                      display:"flex", alignItems:"center", justifyContent:"center", fontSize:16,
                      boxShadow:i < selectedCard.stamps_count ? `0 2px 8px ${style.color}55` : "none",
                    }}>{i < selectedCard.stamps_count ? "★" : ""}</div>
                  ))}
                </div>
                {selectedCard.stamps_count >= merchant.stamps_required && (
                  <div style={{ marginTop:14, padding:"10px 16px", background:`${style.color}22`, color:style.color, borderRadius:10, textAlign:"center", fontWeight:800, fontSize:14 }}>
                    🎉 {merchant.reward_description} disponible !
                  </div>
                )}
              </div>
              <button onClick={() => setSelectedCard(null)} style={{ width:"100%", padding:"14px", background:"#f5f5f5", color:"#555", border:"none", borderRadius:14, fontSize:14, fontWeight:700 }}>Fermer</button>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

// ════════════════════════════════════════════════════════════
//  DASHBOARD COMMERÇANT
// ════════════════════════════════════════════════════════════
function MerchantApp({ token, merchantName, onLogout }) {
  const [tab, setTab]           = useState("dashboard");
  const [merchantInfo, setMerchantInfo] = useState(null);
  const [showScanner, setShowScanner]   = useState(false);
  const [scanPhase, setScanPhase]       = useState("ready");
  const [scanResult, setScanResult]     = useState(null);
  const [toast, setToast]       = useState(null);
  const [confetti, setConfetti] = useState(false);
  const [loading, setLoading]   = useState(true);
  const [qrInput, setQrInput]   = useState("");
  const [program, setProgram]   = useState(null);
  const [savingProgram, setSavingProgram] = useState(false);

  useEffect(() => {
    // Charger les infos du commerçant connecté
    const load = async () => {
      setLoading(true);
      try {
        const merchants = await apiFetch("/merchants/", {}, token);
        // Trouver le merchant de l'utilisateur connecté (on cherche par nom)
        const me = merchants.find(m => m.business_name === merchantName) || merchants[0];
        if (me) {
          setMerchantInfo(me);
          setProgram({ stamps_required: me.stamps_required, reward_description: me.reward_description });
        }
      } catch (e) {
        setToast({ type:"error", title:"Erreur", msg:e.message });
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [token, merchantName]);

  const handleScan = async () => {
    if (!qrInput.trim()) return;
    setScanPhase("scanning");
    await new Promise(r => setTimeout(r, 800));
    setScanPhase("validating");
    try {
      const result = await apiFetch("/scan/", { method:"POST", body:JSON.stringify({ qr_token:qrInput.trim() }) }, token);
      setScanResult(result);
      setScanPhase(result.reward_reached ? "reward" : "success");
      if (result.reward_reached) {
        setConfetti(true);
        setTimeout(() => setConfetti(false), 3000);
        setToast({ type:"success", title:"🏆 Récompense débloquée !", msg:result.message });
      } else {
        setToast({ type:"success", title:"Tampon ajouté !", msg:result.message });
      }
    } catch (e) {
      setScanResult(null);
      setScanPhase("error");
      setToast({ type:"error", title:"Erreur scan", msg:e.message });
    }
  };

  const saveProgram = async () => {
    setSavingProgram(true);
    try {
      // On recrée le merchant avec les nouveaux paramètres via setup
      await apiFetch("/merchants/setup", {
        method:"POST",
        body:JSON.stringify({ business_name:merchantInfo.business_name, category:merchantInfo.category, ...program }),
      }, token);
      setToast({ type:"success", title:"Programme mis à jour !", msg:"Les modifications sont enregistrées." });
    } catch (e) {
      setToast({ type:"error", title:"Erreur", msg:e.message });
    } finally {
      setSavingProgram(false);
    }
  };

  const style = merchantInfo ? getStyle(merchantInfo.category) : getStyle("default");
  const color = style.color;

  return (
    <div style={{ background:"#F7F5F2", minHeight:"100vh", fontFamily:"DM Sans, sans-serif" }}>
      <Confetti active={confetti} />
      <Toast toast={toast} onClose={() => setToast(null)} />

      {/* Top bar */}
      <div style={{ background:"white", borderBottom:"1px solid #EDEAE4", padding:"16px 24px", display:"flex", alignItems:"center", justifyContent:"space-between", position:"sticky", top:0, zIndex:100 }}>
        <div style={{ display:"flex", alignItems:"center", gap:14 }}>
          <div style={{ width:44, height:44, borderRadius:12, background:`${color}15`, display:"flex", alignItems:"center", justifyContent:"center", fontSize:22, border:`1px solid ${color}22` }}>
            {style.emoji}
          </div>
          <div>
            <div style={{ fontWeight:800, fontSize:17, color:"#1A1828" }}>{merchantInfo?.business_name || merchantName}</div>
            <div style={{ fontSize:12, color:"#27AE60", fontWeight:600, display:"flex", alignItems:"center", gap:4 }}>
              <div style={{ width:6, height:6, borderRadius:"50%", background:"#27AE60", animation:"pulse 2s infinite" }} />
              Connecté
            </div>
          </div>
        </div>
        <div style={{ display:"flex", gap:10 }}>
          <button onClick={() => setShowScanner(true)} style={{
            background:`linear-gradient(135deg, ${color}, ${color}cc)`, color:"white",
            borderRadius:12, padding:"10px 20px", fontWeight:700, fontSize:14,
            display:"flex", alignItems:"center", gap:8, boxShadow:`0 4px 16px ${color}44`,
          }}>
            <span style={{ fontSize:18 }}>📷</span> Scanner QR
          </button>
          <button onClick={onLogout} style={{ background:"#f5f5f5", color:"#888", border:"none", borderRadius:10, padding:"10px 14px", fontSize:12, fontWeight:600 }}>Sortir</button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ background:"white", borderBottom:"1px solid #EDEAE4", display:"flex" }}>
        {[{id:"dashboard",label:"Tableau de bord",icon:"📊"},{id:"program",label:"Programme",icon:"⚙️"}].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            flex:1, padding:"13px 8px", fontWeight:600, fontSize:14,
            color:tab===t.id?color:"#6B6880",
            borderBottom:`2px solid ${tab===t.id?color:"transparent"}`,
            background:"none", display:"flex", alignItems:"center", justifyContent:"center", gap:6, transition:"all 0.2s",
          }}><span>{t.icon}</span>{t.label}</button>
        ))}
      </div>

      <div style={{ maxWidth:700, margin:"0 auto", padding:"24px 20px" }}>
        {loading ? (
          <div style={{ display:"flex", justifyContent:"center", padding:"60px 0" }}><Spinner color={color} /></div>
        ) : (
          <>
            {/* ── DASHBOARD ── */}
            {tab === "dashboard" && (
              <div style={{ animation:"fadeUp 0.4s ease" }}>
                {!merchantInfo ? (
                  <div style={{ background:"white", borderRadius:20, padding:"32px", textAlign:"center" }}>
                    <div style={{ fontSize:48, marginBottom:16 }}>⚠️</div>
                    <div style={{ fontWeight:700, fontSize:18, color:"#1A1828", marginBottom:8 }}>Profil non configuré</div>
                    <p style={{ color:"#6B6880", marginBottom:20 }}>Va dans l'onglet Programme pour configurer ton commerce.</p>
                    <button onClick={() => setTab("program")} style={{ background:color, color:"white", borderRadius:12, padding:"12px 24px", fontWeight:700 }}>Configurer →</button>
                  </div>
                ) : (
                  <>
                    {/* Scanner CTA */}
                    <div style={{
                      background:`linear-gradient(135deg, ${color}, ${color}cc)`,
                      borderRadius:20, padding:"24px 28px", marginBottom:24,
                      display:"flex", alignItems:"center", justifyContent:"space-between",
                      cursor:"pointer", boxShadow:`0 8px 32px ${color}44`,
                    }} onClick={() => setShowScanner(true)}>
                      <div>
                        <div style={{ color:"rgba(255,255,255,0.7)", fontSize:13, marginBottom:4 }}>Action principale</div>
                        <div style={{ color:"white", fontSize:20, fontWeight:800 }}>Scanner un client</div>
                        <div style={{ color:"rgba(255,255,255,0.7)", fontSize:13, marginTop:4 }}>Valider un tampon de fidélité</div>
                      </div>
                      <div style={{ width:64, height:64, background:"rgba(255,255,255,0.2)", borderRadius:16, display:"flex", alignItems:"center", justifyContent:"center", fontSize:32, animation:"pulse 2s infinite" }}>📷</div>
                    </div>

                    {/* Infos du programme */}
                    <div style={{ background:"white", borderRadius:20, padding:"20px 22px", boxShadow:"0 2px 12px rgba(0,0,0,0.06)" }}>
                      <div style={{ fontWeight:700, fontSize:15, color:"#1A1828", marginBottom:16 }}>Programme actuel</div>
                      <div style={{ display:"flex", gap:16 }}>
                        <div style={{ flex:1, background:`${color}10`, borderRadius:14, padding:"16px", textAlign:"center" }}>
                          <div style={{ fontSize:32, fontWeight:800, color:color }}>{merchantInfo.stamps_required}</div>
                          <div style={{ fontSize:13, color:"#6B6880", marginTop:4 }}>tampons requis</div>
                        </div>
                        <div style={{ flex:2, background:"#f8f6f3", borderRadius:14, padding:"16px" }}>
                          <div style={{ fontSize:12, color:"#6B6880", marginBottom:4 }}>Récompense</div>
                          <div style={{ fontWeight:700, fontSize:15, color:"#1A1828" }}>🎁 {merchantInfo.reward_description}</div>
                        </div>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}

            {/* ── PROGRAMME ── */}
            {tab === "program" && program && (
              <div style={{ animation:"fadeUp 0.4s ease" }}>
                <div style={{ background:"white", borderRadius:20, padding:"22px", boxShadow:"0 2px 12px rgba(0,0,0,0.06)" }}>
                  <div style={{ fontWeight:700, fontSize:16, color:"#1A1828", marginBottom:20 }}>⚙️ Configuration du programme</div>

                  <div style={{ marginBottom:20 }}>
                    <label style={{ display:"block", fontWeight:600, fontSize:14, color:"#1A1828", marginBottom:6 }}>Nombre de tampons requis</label>
                    <input type="number" min={2} max={50} value={program.stamps_required}
                      onChange={e => setProgram(p => ({ ...p, stamps_required:parseInt(e.target.value)||2 }))}
                      style={{ width:"100%", padding:"12px 14px", border:"2px solid #EDEAE4", borderRadius:12, fontSize:15, outline:"none" }}
                      onFocus={e => e.target.style.borderColor=color}
                      onBlur={e => e.target.style.borderColor="#EDEAE4"}
                    />
                    <div style={{ fontSize:12, color:"#6B6880", marginTop:4 }}>Nombre de visites pour obtenir la récompense</div>
                  </div>

                  <div style={{ marginBottom:20 }}>
                    <label style={{ display:"block", fontWeight:600, fontSize:14, color:"#1A1828", marginBottom:6 }}>Description de la récompense</label>
                    <input value={program.reward_description}
                      onChange={e => setProgram(p => ({ ...p, reward_description:e.target.value }))}
                      placeholder="Ex: 1 café offert"
                      style={{ width:"100%", padding:"12px 14px", border:"2px solid #EDEAE4", borderRadius:12, fontSize:15, outline:"none" }}
                      onFocus={e => e.target.style.borderColor=color}
                      onBlur={e => e.target.style.borderColor="#EDEAE4"}
                    />
                  </div>

                  {/* Aperçu */}
                  <div style={{ background:`${color}10`, border:`1px solid ${color}30`, borderRadius:14, padding:"16px 18px", marginBottom:20 }}>
                    <div style={{ fontSize:13, color:"#6B6880", marginBottom:8 }}>Aperçu</div>
                    <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center" }}>
                      <div>
                        <div style={{ fontWeight:700, fontSize:15, color:"#1A1828" }}>Après {program.stamps_required} visites</div>
                        <div style={{ fontSize:13, color:color, fontWeight:600, marginTop:2 }}>🎁 {program.reward_description}</div>
                      </div>
                      <div style={{ fontSize:32 }}>{style.emoji}</div>
                    </div>
                  </div>

                  <button onClick={saveProgram} disabled={savingProgram} style={{
                    width:"100%", background:`linear-gradient(135deg, ${color}, ${color}cc)`,
                    color:"white", borderRadius:14, padding:"14px", fontWeight:700, fontSize:15,
                    boxShadow:`0 4px 16px ${color}44`, opacity:savingProgram?0.7:1,
                    display:"flex", alignItems:"center", justifyContent:"center", gap:10,
                  }}>
                    {savingProgram ? <Spinner color="white" size={22} /> : "Enregistrer les modifications"}
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* ── MODAL SCANNER ── */}
      {showScanner && (
        <div style={{ position:"fixed", inset:0, background:"rgba(0,0,0,0.92)", zIndex:1000, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", animation:"fadeIn 0.3s ease" }}>
          <button onClick={() => { setShowScanner(false); setScanPhase("ready"); setScanResult(null); setQrInput(""); }} style={{
            position:"absolute", top:20, right:20, background:"rgba(255,255,255,0.1)", color:"white", borderRadius:10, padding:"8px 16px", fontSize:14, fontWeight:600,
          }}>✕ Fermer</button>

          <div style={{ textAlign:"center", color:"white", marginBottom:32 }}>
            <div style={{ fontSize:14, color:"rgba(255,255,255,0.5)", marginBottom:8 }}>{merchantInfo?.business_name}</div>
            <div style={{ fontSize:22, fontWeight:700 }}>
              {scanPhase==="ready"      && "Scanner le QR code client"}
              {scanPhase==="scanning"   && "Lecture..."}
              {scanPhase==="validating" && "Validation en cours..."}
              {scanPhase==="success"    && "✓ Tampon ajouté !"}
              {scanPhase==="reward"     && "🎉 Récompense débloquée !"}
              {scanPhase==="error"      && "✗ QR invalide"}
            </div>
          </div>

          {(scanPhase==="ready") && (
            <div style={{ width:300, padding:"24px", background:"rgba(255,255,255,0.05)", borderRadius:20, border:"1px solid rgba(255,255,255,0.1)" }}>
              <input value={qrInput} onChange={e=>setQrInput(e.target.value)}
                placeholder="Colle le QR token ici..."
                style={{ width:"100%", padding:"14px 16px", borderRadius:12, border:"1.5px solid rgba(255,255,255,0.2)", background:"rgba(255,255,255,0.08)", color:"white", fontSize:13, outline:"none", marginBottom:16, boxSizing:"border-box" }}
                onKeyDown={e => e.key==="Enter" && handleScan()}
              />
              <button onClick={handleScan} style={{ width:"100%", padding:"14px", background:color, color:"white", borderRadius:12, fontWeight:700, fontSize:15 }}>
                Valider le scan
              </button>
              <div style={{ marginTop:12, color:"rgba(255,255,255,0.3)", fontSize:11, textAlign:"center" }}>
                En production : scan caméra direct
              </div>
            </div>
          )}

          {(scanPhase==="scanning" || scanPhase==="validating") && (
            <div style={{ textAlign:"center" }}>
              <Spinner color={color} size={60} />
              <div style={{ color:"rgba(255,255,255,0.5)", fontSize:14, marginTop:20 }}>
                {scanPhase==="scanning" ? "Lecture du QR code..." : "Vérification backend..."}
              </div>
            </div>
          )}

          {(scanPhase==="success" || scanPhase==="reward") && scanResult && (
            <div style={{
              background:"rgba(255,255,255,0.05)", borderRadius:20, padding:32, textAlign:"center",
              animation:"fadeUp 0.4s ease", border:`2px solid ${scanPhase==="reward"?"#F5C842":"#27AE60"}44`, maxWidth:320,
            }}>
              <div style={{ fontSize:64, marginBottom:16 }}>{scanPhase==="reward" ? "🏆" : "✅"}</div>
              <div style={{ color:"white", fontWeight:700, fontSize:18, marginBottom:16 }}>{scanResult.message}</div>
              <div style={{ display:"flex", justifyContent:"center", gap:24, margin:"20px 0" }}>
                <div style={{ textAlign:"center" }}>
                  <div style={{ color:"rgba(255,255,255,0.4)", fontSize:12 }}>Tampons</div>
                  <div style={{ color:color, fontSize:28, fontWeight:800 }}>{scanResult.stamps_count}</div>
                  <div style={{ color:"rgba(255,255,255,0.4)", fontSize:12 }}>/ {scanResult.stamps_required}</div>
                </div>
              </div>
              <button onClick={() => { setScanPhase("ready"); setScanResult(null); setQrInput(""); }} style={{ background:color, color:"white", borderRadius:12, padding:"12px 32px", fontWeight:700, fontSize:15 }}>
                Nouveau scan
              </button>
            </div>
          )}

          {scanPhase==="error" && (
            <div style={{ textAlign:"center" }}>
              <div style={{ fontSize:64, marginBottom:16 }}>❌</div>
              <div style={{ color:"rgba(255,255,255,0.7)", marginBottom:24 }}>QR code invalide ou expiré</div>
              <button onClick={() => { setScanPhase("ready"); setQrInput(""); }} style={{ background:color, color:"white", borderRadius:12, padding:"12px 32px", fontWeight:700 }}>
                Réessayer
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ════════════════════════════════════════════════════════════
//  ROOT APP
// ════════════════════════════════════════════════════════════
export default function App() {
  const [token, setToken]       = useState(() => localStorage.getItem("fp_token") || null);
  const [userType, setUserType] = useState(() => localStorage.getItem("fp_usertype") || null);
  const [userName, setUserName] = useState(() => localStorage.getItem("fp_username") || "");

  const handleAuth = (tok, type, name) => {
    setToken(tok); setUserType(type); setUserName(name);
    localStorage.setItem("fp_token", tok);
    localStorage.setItem("fp_usertype", type);
    localStorage.setItem("fp_username", name);
  };

  const handleLogout = () => {
    setToken(null); setUserType(null); setUserName("");
    localStorage.removeItem("fp_token");
    localStorage.removeItem("fp_usertype");
    localStorage.removeItem("fp_username");
  };

  return (
    <>
      <style>{GLOBAL_CSS}</style>
      {!token && <AuthScreen onAuth={handleAuth} />}
      {token && userType === "client"   && <ClientApp   token={token} userName={userName} onLogout={handleLogout} />}
      {token && userType === "merchant" && <MerchantApp token={token} merchantName={userName} onLogout={handleLogout} />}
    </>
  );
}
