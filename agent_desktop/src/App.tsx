import { useEffect, useMemo, useRef, useState } from "react";
import { provision, refreshProvisioning, revokeProvisioning } from "./api";
import { features } from "./config/features";
import { runtime } from "./config/runtime";
import { audioDevices, microphonePermission, type AudioDevice } from "./devices";
import { emptySnapshot, sanitizedExport, type MediaSnapshot } from "./diagnostics";
import { AiModule } from "./features/ai/AiModule";
import { CallbackModule } from "./features/callbacks/CallbackModule";
import { CrmModule } from "./features/crm/CrmModule";
import { DiagnosticsModule } from "./features/diagnostics/DiagnosticsModule";
import { DispositionModule } from "./features/disposition/DispositionModule";
import { LeadDetailsModule } from "./features/lead/LeadDetailsModule";
import { NotificationsModule } from "./features/notifications/NotificationsModule";
import { PhoneModule } from "./features/phone/PhoneModule";
import { SettingsModule } from "./features/settings/SettingsModule";
import { SupervisorModule } from "./features/supervisor/SupervisorModule";
import { DiagnosticPhone, SipJsPhone, type PhoneAdapter, type PhoneSnapshot } from "./phone";
import { mockDesktopService } from "./services/desktop";
import type { DesktopData } from "./types/desktop";
import { useSingleTab } from "./useSingleTab";
import { RealtimeClient, type RealtimeEvent, type RealtimeState } from "./realtime";
import "./styles.css";

type View = "workspace" | "supervisor" | "diagnostics" | "settings";
const browserSessionId = crypto.randomUUID();

const createPhone = (): PhoneAdapter => {
  if (runtime.environment === "staging" && runtime.sipEnabled && runtime.webRtcEnabled && !runtime.safeMode) {
    return new SipJsPhone({ provision, refresh: refreshProvisioning, revoke: revokeProvisioning });
  }
  return new DiagnosticPhone();
};

export default function App() {
  const phone = useMemo(createPhone, []);
  const duplicate = useSingleTab();
  const remoteAudio = useRef<HTMLAudioElement>(null);
  const [data, setData] = useState<DesktopData>();
  const [view, setView] = useState<View>("workspace");
  const [phoneSnapshot, setPhoneSnapshot] = useState<PhoneSnapshot>(phone.getSnapshot());
  const [inputs, setInputs] = useState<AudioDevice[]>([]);
  const [outputs, setOutputs] = useState<AudioDevice[]>([]);
  const [input, setInput] = useState("");
  const [output, setOutput] = useState("");
  const [message, setMessage] = useState("Staging-only · production routes and transfers disabled");
  const [realtimeState, setRealtimeState] = useState<RealtimeState>("Disconnected");
  const [screenPop, setScreenPop] = useState<RealtimeEvent>();
  const [recordingState, setRecordingState] = useState("Off");
  const realtime = useRef<RealtimeClient | undefined>(undefined);

  useEffect(() => {
    const receiveToken = (raw: Event) => {
      const token = (raw as CustomEvent<string>).detail;
      realtime.current?.disconnect();
      realtime.current = new RealtimeClient(async () => token, event => {
        if (event.type === "call.ringing") setScreenPop(event);
        if (event.type === "recording.started") setRecordingState("ON");
        if (event.type === "recording.available") setRecordingState("Available");
        if (event.type === "session.revoked") realtime.current?.disconnect();
      }, setRealtimeState);
      void realtime.current.connect().catch(error => { setRealtimeState("Disconnected"); setMessage(error instanceof Error ? error.message : "Realtime connection failed"); });
    };
    window.addEventListener("codestra:access-token", receiveToken);
    return () => { window.removeEventListener("codestra:access-token", receiveToken); realtime.current?.disconnect(); };
  }, []);

  useEffect(() => {
    void mockDesktopService.load().then(setData);
    const unsubscribe = phone.subscribe(setPhoneSnapshot);
    void phone.initialize(remoteAudio.current ?? undefined).catch(error => setMessage(error instanceof Error ? error.message : "Phone initialization failed"));
    const refreshDevices = async () => {
      try {
        const permission = await microphonePermission();
        const devices = await audioDevices();
        setInputs(devices.inputs); setOutputs(devices.outputs);
        setPhoneSnapshot(current => ({ ...current, media: { ...current.media, microphonePermission: permission, hasMicrophone: devices.inputs.length > 0 } }));
      } catch { setInputs([]); setOutputs([]); }
    };
    void refreshDevices();
    navigator.mediaDevices?.addEventListener("devicechange", refreshDevices);
    return () => {
      navigator.mediaDevices?.removeEventListener("devicechange", refreshDevices);
      unsubscribe();
      void phone.destroy();
    };
  }, [phone]);

  if (!data) return <div className="loading">Loading staging desktop…</div>;

  const run = async (action: () => Promise<void>, success: string) => {
    try { await action(); setMessage(success); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Phone operation failed"); }
  };
  const register = () => run(async () => {
    if (duplicate) throw new Error("Duplicate browser session detected");
    await phone.requestProvisioningSession({ campaignId: "TEST_SYN", endpoint: "6101", browserSessionId });
    await phone.connect();
    await phone.register();
  }, "Short-lived staging registration complete");
  const micTest = async () => {
    let stream: MediaStream | undefined;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: input ? { deviceId: { exact: input } } : true });
      setMessage("Microphone permission and live track verified; no audio recorded");
    } catch { setMessage("Microphone test failed"); }
    finally { stream?.getTracks().forEach(track => track.stop()); }
  };
  const speakerTest = async () => {
    const context = new AudioContext(), oscillator = context.createOscillator(), gain = context.createGain();
    gain.gain.value = 0.05; oscillator.connect(gain).connect(context.destination); oscillator.start();
    window.setTimeout(() => { oscillator.stop(); void context.close(); }, 500);
  };
  const exportDiagnostics = () => {
    const body = new Blob([sanitizedExport({ timestamp: new Date().toISOString(), snapshot: phoneSnapshot, browser: navigator.userAgent })], { type: "application/json" });
    const anchor = document.createElement("a"); anchor.href = URL.createObjectURL(body); anchor.download = `codestra-diagnostics-${Date.now()}.json`; anchor.click(); URL.revokeObjectURL(anchor.href);
  };
  const callState = phoneSnapshot.state === "INCOMING" ? "Ringing" : phoneSnapshot.state === "ACTIVE" ? "Active" : phoneSnapshot.state === "HELD" ? "Held" : "Idle";
  const registration = phoneSnapshot.state === "REGISTERED" ? "Registered" : ["CONNECTING", "REGISTERING", "PROVISIONING", "RECONNECTING"].includes(phoneSnapshot.state) ? "Connecting" : phoneSnapshot.state === "ERROR" ? "Failed" : "Offline";

  return <div className="app-shell">
    <aside><div className="brand"><i>C</i><span>CODESTRA<small>Agent Desktop</small></span></div>
      <nav>{([["workspace", "Workspace"], ["supervisor", "Supervisor"], ["diagnostics", "Diagnostics"], ["settings", "Settings"]] as [View, string][]).map(([id, label]) => <button className={view === id ? "active" : ""} onClick={() => setView(id)} key={id}>{label}</button>)}</nav>
      <div className="agent"><span>MR</span><div><strong>Maya Rivera</strong><small>WEBSET01 · Setter</small></div></div>
    </aside>
    <main className="workspace"><header className="topbar"><div><small>TEST_SYN · ENDPOINT 6101 · INTERNAL ONLY</small><h1>{view[0].toUpperCase() + view.slice(1)}</h1></div>
      <div className="top-status"><span className="ready-dot"/>{phone.mode} <button onClick={() => setView("diagnostics")}>Phone: {registration}</button><button data-testid="realtime-status">Realtime: {realtimeState}</button><button className="bell" onClick={() => setView("workspace")}>{data.notifications.filter(item => !item.read).length}</button></div></header>
      <audio ref={remoteAudio} autoPlay playsInline aria-label="Remote call audio"/>
      {view === "workspace" && <div className="dashboard-grid">
        {screenPop && <section className="panel" data-testid="screen-pop"><h2>Incoming call</h2><strong>{String(screenPop.payload.customer_name ?? "Customer")}</strong><p>{screenPop.campaign_id} · {String(screenPop.payload.phone ?? "")}</p><a href={`/web#id=${encodeURIComponent(String(screenPop.payload.lead_id ?? ""))}&model=crm.lead&view_type=form`}>Open lead</a></section>}
        <section className="panel" data-testid="recording-state"><h2>Recording</h2><strong>{recordingState}</strong>{recordingState === "Available" && <button>Play</button>}</section>
        {features.phone && <PhoneModule mode={phone.mode} state={phoneSnapshot.state} registration={registration} call={callState} duplicate={duplicate} muted={phoneSnapshot.muted} inputs={inputs} outputs={outputs} input={input} output={output} message={message}
          onInput={value => { setInput(value); void run(() => phone.replaceInputDevice(value), "Microphone changed"); }}
          onOutput={value => { setOutput(value); void run(() => phone.replaceOutputDevice(value), "Speaker changed"); }}
          onRegister={() => void register()} onDisconnect={() => void run(() => phone.disconnect(), "Cleanup complete")}
          onDial={() => void run(() => phone.dial("6000"), "Echo-only call requested")}
          onAnswer={() => void run(() => phone.answer(), "Call answered")} onReject={() => void run(() => phone.reject(), "Call rejected")}
          onMute={() => void run(() => phoneSnapshot.muted ? phone.unmute() : phone.mute(), phoneSnapshot.muted ? "Unmuted" : "Muted")}
          onHold={() => void run(() => phoneSnapshot.held ? phone.resume() : phone.hold(), phoneSnapshot.held ? "Resumed" : "Held")}
          onHangup={() => void run(() => phone.hangup(), "Call ended and media cleaned")}
          onReconnect={() => void run(() => phone.refreshCredentials(), "Credentials refreshed and session recovered")}
          onMicTest={() => void micTest()} onSpeakerTest={() => void speakerTest()}/>}
        <CrmModule lead={data.lead} history={data.history}/><LeadDetailsModule lead={data.lead} onSave={notes => mockDesktopService.saveNotes(data.lead.id, notes)}/>
        <AiModule ai={data.ai}/><DispositionModule onSave={value => mockDesktopService.disposition(data.lead.id, value)}/>
        <CallbackModule onSave={(when, reason) => mockDesktopService.scheduleCallback(data.lead.id, when, reason)}/><NotificationsModule items={data.notifications}/>
      </div>}
      {view === "supervisor" && <SupervisorModule team={data.team}/>}
      {view === "diagnostics" && <DiagnosticsModule snapshot={phoneSnapshot.media ?? emptySnapshot} onExport={exportDiagnostics}/>}
      {view === "settings" && <SettingsModule/>}
    </main>
  </div>;
}
