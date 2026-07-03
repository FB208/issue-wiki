import { createContext, startTransition, useContext, useDeferredValue, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Link, NavLink, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import MDEditor, { commands } from "@uiw/react-md-editor";
import "@uiw/react-md-editor/markdown-editor.css";
import "@uiw/react-markdown-preview/markdown.css";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";

import { request, setToken, toQuery, uploadFile } from "./api.js";

const statusOptions = [
  { value: "pending_review", label: "待审核" },
  { value: "pending_start", label: "待启动" },
  { value: "in_progress", label: "进行中" },
  { value: "completed", label: "已完成" },
];

const sourceOptions = [
  { value: "admin", label: "管理员" },
  { value: "user", label: "用户" },
  { value: "github", label: "GitHub" },
];

const visibilityOptions = [
  { value: "all", label: "全部可见性" },
  { value: "visible", label: "仅公开" },
  { value: "hidden", label: "仅隐藏" },
];

const githubSyncOptions = [
  { value: "all", label: "全部同步状态" },
  { value: "unbound", label: "未绑定 Issue" },
  { value: "pending", label: "待同步" },
  { value: "synced", label: "已同步" },
  { value: "error", label: "同步失败" },
];

const defaultStatuses = ["pending_start", "in_progress"];
const defaultPageParams = { page: 1, page_size: 20 };
const pageSizeOptions = [10, 20, 50];
const defaultSponsorAmount = "100";
const sponsorAmountOptions = ["10", "50", "100", "1000"];
const avatarColors = ["#2563eb", "#059669", "#7c3aed", "#db2777", "#ea580c", "#0891b2", "#4f46e5", "#16a34a"];
const htmlMarkdownOptions = { remarkPlugins: [remarkGfm], rehypePlugins: [rehypeRaw] };

function avatarInitial(nickname) {
  const text = String(nickname || "用户").trim();
  return Array.from(text)[0] || "用";
}

function avatarColor(user) {
  const source = `${user?.id || ""}:${user?.nickname || "用户"}`;
  let hash = 0;
  for (let index = 0; index < source.length; index += 1) {
    hash = ((hash << 5) - hash + source.charCodeAt(index)) | 0;
  }
  return avatarColors[Math.abs(hash) % avatarColors.length];
}

function createDefaultAdminTaskFilters() {
  return {
    name: "",
    status: [],
    sort_by: "sort_order",
    sort_order: "asc",
    source: [],
    visibility: "all",
    github_sync: "all",
  };
}

function createDefaultTaskForm() {
  return { name: "", description: "", start_amount: "0", sort_order: "", status: "pending_start", is_hidden: false };
}

function createDefaultDocumentForm() {
  return { title: "", content: "", folder_id: "", sort_order: "" };
}

function createDefaultFolderForm() {
  return { name: "", parent_id: "", sort_order: "" };
}

function taskFormPayload(form) {
  return {
    name: form.name,
    description: form.description,
    start_amount: form.start_amount,
    sort_order: form.sort_order === "" ? undefined : Number(form.sort_order),
    status: form.status,
    is_hidden: form.is_hidden,
  };
}

function documentFormPayload(form) {
  const payload = {
    title: form.title,
    content: form.content,
    folder_id: form.folder_id ? Number(form.folder_id) : null,
  };
  if (form.sort_order !== "") payload.sort_order = Number(form.sort_order);
  return payload;
}

function folderFormPayload(form) {
  const payload = {
    name: form.name,
    parent_id: form.parent_id ? Number(form.parent_id) : null,
  };
  if (form.sort_order !== "") payload.sort_order = Number(form.sort_order);
  return payload;
}

function emptyPage(params = defaultPageParams) {
  return { items: [], total: 0, page: params.page, page_size: params.page_size, pages: 1 };
}

function pageItems(pageData) {
  return pageData?.items || [];
}

function loadingText(isBusy, idleText, busyText = "处理中...") {
  return isBusy ? busyText : idleText;
}

function useBusyActions() {
  const busyRef = useRef(new Set());
  const [, setBusyVersion] = useState(0);

  function busy(key) {
    return busyRef.current.has(key);
  }

  async function runBusy(key, action) {
    if (busyRef.current.has(key)) return undefined;
    busyRef.current.add(key);
    setBusyVersion((value) => value + 1);
    try {
      return await action();
    } finally {
      busyRef.current.delete(key);
      setBusyVersion((value) => value + 1);
    }
  }

  return { busy, runBusy };
}

let overlayLockCount = 0;
let previousBodyOverflow = "";
let previousBodyPaddingRight = "";

function useOverlayFocus(containerRef, close, enabled = true) {
  useEffect(() => {
    if (!enabled) return undefined;
    const previousActiveElement = document.activeElement;
    const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
    if (overlayLockCount === 0) {
      previousBodyOverflow = document.body.style.overflow;
      previousBodyPaddingRight = document.body.style.paddingRight;
      document.body.style.overflow = "hidden";
      if (scrollbarWidth > 0) document.body.style.paddingRight = `${scrollbarWidth}px`;
    }
    overlayLockCount += 1;
    window.requestAnimationFrame(() => containerRef.current?.focus());
    return () => {
      overlayLockCount = Math.max(0, overlayLockCount - 1);
      if (overlayLockCount === 0) {
        document.body.style.overflow = previousBodyOverflow;
        document.body.style.paddingRight = previousBodyPaddingRight;
      }
      if (previousActiveElement instanceof HTMLElement) previousActiveElement.focus();
    };
  }, [containerRef, enabled]);

  function handleOverlayKeyDown(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = containerRef.current?.querySelectorAll(
      'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    const nodes = Array.from(focusable || []).filter((node) => node.offsetParent !== null);
    if (!nodes.length) {
      event.preventDefault();
      containerRef.current?.focus();
      return;
    }
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return handleOverlayKeyDown;
}

const ToastContext = createContext(() => {});
let nextToastId = 0;

function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  function notify(message, type = "success") {
    const id = nextToastId += 1;
    setToasts((current) => [...current, { id, message, type }].slice(-4));
    window.setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== id));
    }, 2200);
  }

  return (
    <ToastContext.Provider value={notify}>
      {children}
      <div className="toast-stack" aria-live="polite" aria-atomic="true">
        {toasts.map((item) => <div key={item.id} className={`toast ${item.type}`}>{item.message}</div>)}
      </div>
    </ToastContext.Provider>
  );
}

function useToast() {
  return useContext(ToastContext);
}

export default function App() {
  const [user, setUser] = useState(null);
  const [nav, setNav] = useState({ folders: [], documents: [] });
  const [paymentSummary, setPaymentSummary] = useState({ paid_amount: "0" });
  const [sponsorRanking, setSponsorRanking] = useState([]);
  const [authOpen, setAuthOpen] = useState(false);
  const [authorTipOpen, setAuthorTipOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  async function loadUser() {
    try {
      const me = await request("/auth/me");
      setUser(me);
    } catch {
      setUser(null);
    }
  }

  async function loadNavigation() {
    try {
      setNav(await request("/navigation"));
    } catch {
      setNav({ folders: [], documents: [] });
    }
  }

  async function loadPaymentSummary() {
    try {
      setPaymentSummary(await request("/payments/summary"));
    } catch {
      setPaymentSummary({ paid_amount: "0" });
    }
  }

  async function loadSponsorRanking() {
    try {
      setSponsorRanking(await request("/payments/ranking"));
    } catch {
      setSponsorRanking([]);
    }
  }

  async function refreshSponsorData() {
    await Promise.all([loadPaymentSummary(), loadSponsorRanking()]);
  }

  useEffect(() => {
    loadUser();
    loadNavigation();
    loadPaymentSummary();
    loadSponsorRanking();
  }, []);

  function logout() {
    setToken("");
    setUser(null);
  }

  return (
    <ToastProvider>
      <Layout nav={nav} user={user} logout={logout} openAuth={() => setAuthOpen(true)} openAuthorTip={() => setAuthorTipOpen(true)} mobileOpen={mobileOpen} setMobileOpen={setMobileOpen}>
        <Routes>
          <Route path="/" element={<HomePage user={user} openAuth={() => setAuthOpen(true)} paidAmount={paymentSummary.paid_amount} sponsorRanking={sponsorRanking} refreshPaymentSummary={refreshSponsorData} />} />
          <Route path="/thanks" element={<SponsorThanksPage sponsorRanking={sponsorRanking} />} />
          <Route path="/tasks/:taskId" element={<TaskDetailPage user={user} openAuth={() => setAuthOpen(true)} />} />
          <Route path="/docs" element={<DocumentsPage nav={nav} user={user} openAuth={() => setAuthOpen(true)} />} />
          <Route path="/docs/:documentId" element={<DocumentsPage nav={nav} user={user} openAuth={() => setAuthOpen(true)} />} />
          <Route path="/mine/tasks" element={<MinePage type="tasks" user={user} openAuth={() => setAuthOpen(true)} />} />
          <Route path="/mine/orders" element={<MinePage type="orders" user={user} openAuth={() => setAuthOpen(true)} />} />
          <Route path="/settings" element={<SettingsPage user={user} openAuth={() => setAuthOpen(true)} onUserUpdated={setUser} />} />
          <Route path="/admin/*" element={<AdminPage user={user} openAuth={() => setAuthOpen(true)} refreshNav={loadNavigation} />} />
        </Routes>
      </Layout>
      {authOpen && <AuthModal close={() => setAuthOpen(false)} onAuthed={loadUser} />}
      {authorTipOpen && <SponsorModal close={() => setAuthorTipOpen(false)} onDone={refreshSponsorData} />}
    </ToastProvider>
  );
}

function Layout({ children, nav, user, logout, openAuth, openAuthorTip, mobileOpen, setMobileOpen }) {
  return (
    <div className="shell">
      <button className="mobile-menu" onClick={() => setMobileOpen(true)}>菜单</button>
      <aside className={`sidebar ${mobileOpen ? "open" : ""}`}>
        <div className="brand">
          <img className="logo" src="/logo.png" alt="Issue Wiki" />
          <div>
            <b>Issue Wiki</b>
            <span>开源任务控制台</span>
          </div>
        </div>
        <button className="sidebar-close" onClick={() => setMobileOpen(false)}>关闭</button>
        <nav className="nav" onClick={() => setMobileOpen(false)}>
          <div className="nav-label">工作区</div>
          <NavLink to="/" end>赞助功能 <span className="badge">首页</span></NavLink>
          <NavLink to="/thanks">鸣谢清单</NavLink>
          {user && <NavLink to="/mine/tasks">我的需求</NavLink>}
          {user && <NavLink to="/mine/orders">我的赞助</NavLink>}
          {user?.role === "admin" && <NavLink to="/admin">管理员后台</NavLink>}
          <div className="nav-label">文档</div>
          <DocumentTreeNav nav={nav} />
        </nav>
      </aside>
      {mobileOpen && <div className="overlay" onClick={() => setMobileOpen(false)} />}
      <main className="main">
        <header className="topbar">
          <div className="top-actions">
            {user ? <Link className="user-chip" to="/settings"><UserAvatar user={user} size="sm" /><span>{user.nickname}</span></Link> : <button className="btn" onClick={openAuth}>登录</button>}
            {user ? <button className="btn ghost" onClick={logout}>退出</button> : null}
            <button className="btn primary" onClick={openAuthorTip}>打赏作者</button>
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}

function UserAvatar({ user, size = "md" }) {
  const avatarUrl = user?.avatar_url || "";
  const nickname = user?.nickname || "用户";
  return (
    <span className={`avatar avatar-${size}`} style={{ "--avatar-bg": avatarColor(user) }} aria-hidden="true">
      {avatarUrl ? <img src={avatarUrl} alt="" /> : <span>{avatarInitial(nickname)}</span>}
    </span>
  );
}

function DocumentTreeNav({ nav }) {
  const location = useLocation();
  const folders = nav.folders || [];
  const documents = nav.documents || [];
  const [collapsedFolders, setCollapsedFolders] = useState(() => new Set());
  const folderMap = new Map(folders.map((folder) => [folder.id, folder]));
  const folderChildren = new Map();
  const topFolders = [];
  const docsByFolder = new Map();
  const rootDocuments = [];
  const activeDocId = location.pathname.startsWith("/docs/") ? Number(location.pathname.split("/").pop()) : null;
  const activeDocument = documents.find((doc) => Number(doc.id) === activeDocId);
  const activeFolderIds = new Set();

  folders.forEach((folder) => {
    if (folder.parent_id && folderMap.has(folder.parent_id)) {
      const children = folderChildren.get(folder.parent_id) || [];
      children.push(folder);
      folderChildren.set(folder.parent_id, children);
    } else {
      topFolders.push(folder);
    }
  });

  documents.forEach((doc) => {
    if (doc.folder_id && folderMap.has(doc.folder_id)) {
      const docs = docsByFolder.get(doc.folder_id) || [];
      docs.push(doc);
      docsByFolder.set(doc.folder_id, docs);
    } else {
      rootDocuments.push(doc);
    }
  });

  let currentFolderId = activeDocument?.folder_id;
  while (currentFolderId && folderMap.has(currentFolderId)) {
    activeFolderIds.add(currentFolderId);
    currentFolderId = folderMap.get(currentFolderId).parent_id;
  }

  function toggleFolder(event, folderId) {
    event.stopPropagation();
    setCollapsedFolders((current) => {
      const next = new Set(current);
      if (next.has(folderId)) next.delete(folderId);
      else next.add(folderId);
      return next;
    });
  }

  function docLink(doc, depth) {
    return (
      <NavLink key={doc.id} className={({ isActive }) => `doc-nav-link${isActive ? " active" : ""}`} style={{ paddingLeft: `${12 + depth * 14}px` }} to={`/docs/${doc.id}`} end>
        {doc.title}
      </NavLink>
    );
  }

  function folderGroup(folder, depth = 0, ancestors = new Set()) {
    if (ancestors.has(folder.id)) return null;
    const nextAncestors = new Set(ancestors);
    nextAncestors.add(folder.id);
    const childFolders = folderChildren.get(folder.id) || [];
    const folderDocs = docsByFolder.get(folder.id) || [];
    const hasChildren = childFolders.length > 0 || folderDocs.length > 0;
    const isActive = activeFolderIds.has(folder.id);
    const isOpen = isActive || !collapsedFolders.has(folder.id);
    return (
      <div key={folder.id} className="nav-folder">
        <button
          type="button"
          className={`nav-folder-toggle${isActive ? " active" : ""}`}
          style={{ paddingLeft: `${12 + depth * 14}px` }}
          aria-expanded={isOpen}
          onClick={(event) => toggleFolder(event, folder.id)}
        >
          <span>{folder.name}</span>
          {hasChildren ? <span className="nav-folder-chevron">{isOpen ? "v" : ">"}</span> : null}
        </button>
        {hasChildren && isOpen ? (
          <div className="nav-folder-items">
            {childFolders.map((child) => folderGroup(child, depth + 1, nextAncestors))}
            {folderDocs.map((doc) => docLink(doc, depth + 1))}
          </div>
        ) : null}
      </div>
    );
  }

  if (!folders.length && !documents.length) return <div className="nav-empty">暂无文档</div>;

  return (
    <div className="nav-docs">
      {rootDocuments.map((doc) => docLink(doc, 0))}
      {topFolders.map((folder) => folderGroup(folder))}
    </div>
  );
}

function HomePage({ user, openAuth, paidAmount, sponsorRanking, refreshPaymentSummary }) {
  const [tasksPage, setTasksPage] = useState(() => emptyPage());
  const [pagination, setPagination] = useState(defaultPageParams);
  const [heroContent, setHeroContent] = useState("");
  const [filters, setFilters] = useState({ name: "", status: defaultStatuses, sort_by: "sort_order", sort_order: "asc" });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [demandOpen, setDemandOpen] = useState(false);
  const [sponsorTask, setSponsorTask] = useState(null);
  const deferredName = useDeferredValue(filters.name);

  async function loadTasks() {
    setLoading(true);
    setError("");
    try {
      const query = toQuery({ name: deferredName, status: filters.status, sort_by: filters.sort_by, sort_order: filters.sort_order, ...pagination });
      setTasksPage(await request(`/tasks${query}`));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadHeroContent() {
    const result = await request("/site/home-hero");
    setHeroContent(result.content);
  }

  useEffect(() => {
    loadHeroContent().catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    loadTasks();
  }, [deferredName, filters.status.join(","), filters.sort_by, filters.sort_order, pagination.page, pagination.page_size]);

  function updateFilter(next) {
    startTransition(() => setFilters((current) => ({ ...current, ...next })));
    setPagination((current) => ({ ...current, page: 1 }));
  }

  async function refreshAfterSponsorPaid() {
    await Promise.all([loadTasks(), refreshPaymentSummary?.()]);
  }

  const tasks = pageItems(tasksPage);
  const totalSponsored = Number(paidAmount || 0);
  const coCreators = tasks.reduce((sum, task) => sum + Number(task.co_creator_count || 0), 0);

  return (
    <>
      <section className="hero-card">
        <div className="hero-content">
          <ReactMarkdown {...htmlMarkdownOptions}>{heroContent}</ReactMarkdown>
        </div>
        <div className="hero-side">
          <div className="summary-grid">
            <Metric title="公开任务" value={tasksPage.total} />
            <Metric title="已赞助" value={formatMoney(totalSponsored)} />
            <Metric title="共创人数" value={coCreators} />
          </div>
          <SponsorRanking items={sponsorRanking} limit={3} includeGuest={false} />
        </div>
      </section>

      <section className="panel">
        <div className="panel-head stacked">
          <div><h2>任务列表</h2><p>默认展示待启动和进行中的任务，前三名展示金银铜效果。</p></div>
          <div className="filters">
            <input value={filters.name} placeholder="任务名称模糊查询" onChange={(event) => updateFilter({ name: event.target.value })} />
            <select value={filters.sort_by} onChange={(event) => updateFilter({ sort_by: event.target.value })}>
              <option value="sort_order">顺序</option>
              <option value="name">名称</option>
              <option value="start_amount">启动资金</option>
              <option value="donated_amount">已赞助金额</option>
            </select>
            <select value={filters.sort_order} onChange={(event) => updateFilter({ sort_order: event.target.value })}>
              <option value="asc">升序</option>
              <option value="desc">降序</option>
            </select>
          </div>
          <div className="status-filter">
            {statusOptions.map((item) => (
              <label key={item.value}>
                <input
                  type="checkbox"
                  checked={filters.status.includes(item.value)}
                  onChange={(event) => {
                    const next = event.target.checked ? [...filters.status, item.value] : filters.status.filter((value) => value !== item.value);
                    updateFilter({ status: next });
                  }}
                />
                {item.label}
              </label>
            ))}
          </div>
          <button className="btn primary" onClick={() => (user ? setDemandOpen(true) : openAuth())}>提需求</button>
        </div>
        {error && <Notice type="error" message={error} />}
        {loading ? <div className="empty">加载中...</div> : <TaskTable tasks={tasks} startIndex={(tasksPage.page - 1) * tasksPage.page_size} onSponsor={setSponsorTask} />}
        <Pagination pageData={tasksPage} loading={loading} onChange={(next) => setPagination((current) => ({ ...current, ...next }))} />
      </section>

      {demandOpen && <DemandModal user={user} openAuth={openAuth} close={() => setDemandOpen(false)} onDone={loadTasks} />}
      {sponsorTask && <SponsorModal task={sponsorTask} close={() => setSponsorTask(null)} onDone={refreshAfterSponsorPaid} />}
    </>
  );
}

function Metric({ title, value }) {
  return <div className="metric"><span>{title}</span><b>{value}</b></div>;
}

function SponsorRanking({ items, title = "赞助排行", limit = null, includeGuest = true }) {
  let ranking = Array.isArray(items) ? items : [];
  if (!includeGuest) ranking = ranking.filter((item) => !item.is_guest);
  if (limit) ranking = ranking.slice(0, limit);
  return (
    <div className="sponsor-ranking">
      <div className="sponsor-ranking-head">
        <h3>{title}</h3>
      </div>
      {!ranking.length ? <div className="sponsor-ranking-empty">暂无赞助记录</div> : (
        <div className="sponsor-ranking-list">
          {ranking.map((item, index) => {
            const user = { id: item.user_id ?? "guest", nickname: item.nickname, avatar_url: item.avatar_url };
            return (
              <div key={item.is_guest ? "guest" : item.user_id} className={`sponsor-ranking-item${item.is_guest ? " guest" : ""}`}>
                <span className="sponsor-rank">{item.is_guest ? "游客" : index + 1}</span>
                <div className="sponsor-ranking-user"><UserAvatar user={user} size="sm" /><span>{item.nickname}</span></div>
                <b>{formatMoney(item.amount)}</b>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function SponsorThanksPage({ sponsorRanking }) {
  return <section className="thanks-page"><SponsorRanking items={sponsorRanking} title="鸣谢清单" /></section>;
}

function TaskTable({ tasks, onSponsor, startIndex = 0 }) {
  if (!tasks.length) return <div className="empty">暂无任务</div>;
  return (
    <>
      <div className="desktop-table">
        <table>
          <thead><tr><th>顺序</th><th>标题</th><th>创建日期</th><th>启动资金</th><th>已赞助</th><th>共创人数</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            {tasks.map((task, index) => <TaskRow key={task.id} task={task} index={startIndex + index} onSponsor={onSponsor} />)}
          </tbody>
        </table>
      </div>
      <div className="mobile-cards">
        {tasks.map((task, index) => <TaskCard key={task.id} task={task} index={startIndex + index} onSponsor={onSponsor} />)}
      </div>
    </>
  );
}

function TaskRow({ task, index, onSponsor }) {
  return (
    <tr>
      <td><Rank index={index} value={task.sort_order} /></td>
      <td><Link className="task-title-link" to={`/tasks/${task.id}`}><b>{task.name}</b></Link></td>
      <td>{formatDate(task.created_at)}</td>
      <td>¥{task.start_amount}</td>
      <td>¥{task.donated_amount}</td>
      <td>{task.co_creator_count}</td>
      <td><span className="status">{task.status_label}</span></td>
      <td><Link className="link-btn" to={`/tasks/${task.id}`}>共创</Link><button className="link-btn" onClick={() => onSponsor(task)}>赞助</button></td>
    </tr>
  );
}

function TaskCard({ task, index, onSponsor }) {
  return (
    <article className="task-card">
      <div className="task-card-head"><Rank index={index} value={task.sort_order} /><span className="status">{task.status_label}</span></div>
      <h3><Link className="task-title-link" to={`/tasks/${task.id}`}>{task.name}</Link></h3>
      <div className="card-stats"><span>启动 ¥{task.start_amount}</span><span>已赞助 ¥{task.donated_amount}</span><span>共创 {task.co_creator_count}</span></div>
      <div className="row-actions"><Link className="btn" to={`/tasks/${task.id}`}>共创</Link><button className="btn primary" onClick={() => onSponsor(task)}>赞助</button></div>
    </article>
  );
}

function Rank({ index, value }) {
  const cls = index === 0 ? "gold" : index === 1 ? "silver" : index === 2 ? "bronze" : "plain";
  return <span className={`rank ${cls}`}>{index < 3 ? index + 1 : value}</span>;
}

function DemandModal({ user, openAuth, close, onDone }) {
  const [form, setForm] = useState({ name: "", description: "" });
  const [drawerHeight, setDrawerHeight] = useState(72);
  const [error, setError] = useState("");
  const notify = useToast();
  const { busy, runBusy } = useBusyActions();
  const submitting = busy("submit-demand");

  async function submit(event) {
    event.preventDefault();
    setError("");
    await runBusy("submit-demand", async () => {
      await request("/tasks/demands", { method: "POST", body: JSON.stringify(form) });
      await onDone();
      notify("需求已提交");
      close();
    }).catch((err) => setError(err.message));
  }

  return (
    <BottomDrawer title="提需求" open height={drawerHeight} setHeight={setDrawerHeight} close={close}>
      <form className="form drawer-form" onSubmit={submit}>
        <input placeholder="需求名称" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
        <MarkdownEditor value={form.description} onChange={(description) => setForm({ ...form, description })} user={user} openAuth={openAuth} fill />
        {error && <Notice type="error" message={error} />}
        <div className="drawer-actions"><button type="button" className="btn" onClick={close}>取消</button><button className="btn primary" disabled={submitting} aria-busy={submitting}>{loadingText(submitting, "提交需求", "提交中...")}</button></div>
      </form>
    </BottomDrawer>
  );
}

function SponsorModal({ task, close, onDone }) {
  const [paymentConfig, setPaymentConfig] = useState(null);
  const [amount, setAmount] = useState(defaultSponsorAmount);
  const [intent, setIntent] = useState(null);
  const [polling, setPolling] = useState(false);
  const [error, setError] = useState("");
  const notify = useToast();
  const { busy, runBusy } = useBusyActions();
  const creating = busy("create-sponsor-order");
  const isTaskSponsor = Boolean(task);
  const featureId = isTaskSponsor ? `IW-TASK-${task.id}` : "";
  const sponsorTitle = isTaskSponsor ? `赞助：${task.name}` : "打赏作者";
  const sponsorEndpoint = isTaskSponsor ? `/tasks/${task.id}/sponsor` : "/payments/tip";
  const amountLabel = isTaskSponsor ? "赞助金额" : "打赏金额";
  const channel = paymentConfig?.channel;
  const isAfdian = channel === "afdian";
  const isXorpay = channel === "xorpay";
  const afdianActionText = isTaskSponsor ? "前往爱发电赞助" : "前往爱发电打赏";

  useEffect(() => {
    let active = true;
    request("/payments/config").then((result) => {
      if (!active) return;
      setPaymentConfig(result);
    }).catch((err) => {
      if (active) setError(err.message);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (intent?.channel !== "xorpay" || !intent.merchant_order_no || ["paid", "failed", "closed"].includes(intent.status)) return undefined;
    let stopped = false;
    async function pollOrder() {
      setPolling(true);
      try {
        const order = await request(`/payments/orders/${encodeURIComponent(intent.merchant_order_no)}`);
        if (stopped) return;
        if (order.status === "paid") {
          setIntent((current) => ({ ...current, status: "paid" }));
          notify(isTaskSponsor ? "支付成功，已更新赞助金额" : "支付成功，感谢打赏");
          await onDone?.();
        } else if (order.status === "failed" || order.status === "closed") {
          setIntent((current) => ({ ...current, status: order.status }));
          setError("订单未完成，请重新生成支付二维码");
        }
      } catch (err) {
        if (!stopped) setError(err.message);
      } finally {
        if (!stopped) setPolling(false);
      }
    }
    const firstTimer = window.setTimeout(pollOrder, 1500);
    const timer = window.setInterval(pollOrder, 3000);
    return () => {
      stopped = true;
      window.clearTimeout(firstTimer);
      window.clearInterval(timer);
    };
  }, [intent?.channel, intent?.merchant_order_no, intent?.status]);

  async function submit(event) {
    event.preventDefault();
    setError("");
    await runBusy("create-sponsor-order", async () => {
      if (!paymentConfig) throw new Error("支付配置加载中");
      if (isAfdian) {
        const result = await request(sponsorEndpoint, { method: "POST" });
        if (!result.payment_url) throw new Error("爱发电赞助链接未配置");
        window.location.href = result.payment_url;
        return;
      }
      const result = await request(sponsorEndpoint, { method: "POST", body: JSON.stringify({ amount }) });
      setIntent(result);
      notify("订单已创建，请使用微信扫码支付");
    }).catch((err) => setError(err.message));
  }

  async function copyFeatureId() {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(featureId);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = featureId;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        document.body.removeChild(textarea);
      }
      notify("已复制功能 ID");
    } catch (err) {
      setError(err.message || "复制失败，请手动复制功能 ID");
    }
  }

  return (
    <Modal title={sponsorTitle} close={close}>
      <form className="form" onSubmit={submit}>
        {!paymentConfig && !error && <div className="empty">加载支付配置...</div>}
        {isAfdian && (
          <>
            {isTaskSponsor ? (
              <>
                <p className="sponsor-warning">赞助某功能需要在支付时备注功能ID，参考下图：</p>
                <img className="sponsor-example-image" src="/afdian-remark-example.png" alt="爱发电备注功能ID示例" />
                <div className="feature-id-box">
                  <span>{featureId}</span>
                  <button type="button" className="btn" onClick={copyFeatureId}>复制 ID</button>
                </div>
              </>
            ) : <p className="sponsor-warning">点击后将前往爱发电打赏作者，无需填写功能 ID。</p>}
          </>
        )}
        {isXorpay && (
          <>
            <label>{amountLabel}
              <input type="number" min={paymentConfig.xorpay_min_order_amount} step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} />
            </label>
            <div className="amount-shortcuts" aria-label="快捷选择金额">
              {sponsorAmountOptions.map((option) => (
                <button
                  key={option}
                  type="button"
                  className={`btn amount-shortcut${Number(amount) === Number(option) ? " active" : ""}`}
                  onClick={() => setAmount(option)}
                >
                  ¥{option}
                </button>
              ))}
            </div>
            <p className="muted">当前最小订单金额：¥{paymentConfig.xorpay_min_order_amount}。提交后会生成微信扫码支付二维码。</p>
            {intent?.qr_image_url && (
              <div className="sponsor-payment-card">
                <img className="sponsor-qr" src={intent.qr_image_url} alt="微信支付二维码" />
                <div className="sponsor-order-meta">
                  <b>{intent.status === "paid" ? "支付成功" : "等待支付"}</b>
                  <span>订单号：{intent.merchant_order_no}</span>
                  <span>金额：¥{intent.amount}</span>
                  {intent.expires_in ? <span>二维码有效期约 {Math.ceil(intent.expires_in / 60)} 分钟</span> : null}
                  {polling && intent.status !== "paid" ? <span>正在等待支付结果...</span> : null}
                </div>
              </div>
            )}
          </>
        )}
        {error && <Notice type="error" message={error} />}
        <button className="btn primary" disabled={creating || !paymentConfig || (isXorpay && !amount)} aria-busy={creating}>
          {loadingText(creating, isAfdian ? afdianActionText : "生成微信支付二维码", isAfdian ? "打开中..." : "创建中...")}
        </button>
      </form>
    </Modal>
  );
}

function TaskDetailPage({ user, openAuth }) {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const [task, setTask] = useState(null);
  const [commentsPage, setCommentsPage] = useState(() => emptyPage());
  const [pagination, setPagination] = useState(defaultPageParams);
  const [loading, setLoading] = useState(true);
  const [replyDrawerOpen, setReplyDrawerOpen] = useState(false);
  const [replyDrawerHeight, setReplyDrawerHeight] = useState(56);
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  const notify = useToast();
  const { busy, runBusy } = useBusyActions();
  const submitting = task ? busy(`submit-task-comment-${task.id}`) : false;

  useEffect(() => {
    setTask(null);
    setCommentsPage(emptyPage());
    setError("");
    setPagination(defaultPageParams);
    setReplyDrawerOpen(false);
    setContent("");
  }, [taskId]);

  async function loadTask() {
    if (!taskId) return;
    setLoading(true);
    setError("");
    try {
      const [taskResult, comments] = await Promise.all([
        request(`/tasks/${taskId}`),
        request(`/tasks/${taskId}/comments${toQuery(pagination)}`),
      ]);
      setTask(taskResult);
      setCommentsPage(comments);
    } catch (err) {
      setTask(null);
      setCommentsPage(emptyPage());
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadTask(); }, [taskId, pagination.page, pagination.page_size]);

  function goBack() {
    if (window.history.length > 1) navigate(-1);
    else navigate("/");
  }

  function openReplyDrawer() {
    if (!user) return openAuth();
    if (task?.status === "completed") return;
    setError("");
    setContent("");
    setReplyDrawerOpen(true);
  }

  function closeReplyDrawer() {
    setReplyDrawerOpen(false);
    setContent("");
  }

  async function submit(event) {
    event.preventDefault();
    if (!task) return;
    if (!user) return openAuth();
    const value = content.trim();
    if (!value) return;
    setError("");
    await runBusy(`submit-task-comment-${task.id}`, async () => {
      await request(`/tasks/${task.id}/comments`, { method: "POST", body: JSON.stringify({ content: value }) });
      closeReplyDrawer();
      await loadTask();
      notify("评论已发布，GitHub 后台同步中");
    }).catch((err) => setError(err.message));
  }

  if (!task) {
    return <section className="panel"><div className="empty">{loading ? "加载中..." : error || "任务不存在"}</div></section>;
  }

  const completed = task.status === "completed";

  return (
    <>
      <div className="page-back-row"><button className="btn ghost" onClick={goBack}>返回</button></div>
      {error && <Notice type="error" message={error} />}
      <section className="doc-layout task-page-layout">
        <article className="panel doc-panel">
          <div className="doc-head">
            <div><span className="label">任务</span><h2>{task.name}</h2><p>创建于 {formatDate(task.created_at)}，更新于 {formatDate(task.updated_at)}</p></div>
            <div className="row-actions">
              <span className="status">{task.status_label}</span>
              {task.github_issue_url && <a className="btn" href={task.github_issue_url} target="_blank" rel="noreferrer">GitHub Issue</a>}
              <button className="btn primary" disabled={completed} onClick={openReplyDrawer}>{completed ? "已完成" : "发起共创"}</button>
            </div>
          </div>
          <div className="task-meta-grid">
            <DetailItem label="启动资金" value={`¥${task.start_amount}`} />
            <DetailItem label="已赞助" value={`¥${task.donated_amount}`} />
            <DetailItem label="共创人数" value={task.co_creator_count} />
            <DetailItem label="排序" value={task.sort_order} />
          </div>
          {completed && <Notice message="已完成任务不能继续共创，但仍可赞助。" />}
          <div className="markdown-body task-page-body"><ReactMarkdown remarkPlugins={[remarkGfm]}>{task.description || "暂无描述"}</ReactMarkdown></div>
        </article>
        <section className="panel comments-panel document-comments-panel">
          <div className="panel-head"><h2>共创评论</h2><button className="btn" disabled={completed} onClick={openReplyDrawer}>{completed ? "已完成" : "发起评论"}</button></div>
          <div className="comment-list compact">
            {loading ? <div className="empty">加载中...</div> : pageItems(commentsPage).map((item) => <Comment key={item.id} item={item} />)}
            {!loading && !commentsPage.items.length && <div className="empty">暂无共创评论</div>}
          </div>
          <Pagination pageData={commentsPage} loading={loading} onChange={(next) => setPagination((current) => ({ ...current, ...next }))} />
        </section>
      </section>
      <BottomDrawer title="发布共创评论" open={replyDrawerOpen} height={replyDrawerHeight} setHeight={setReplyDrawerHeight} close={closeReplyDrawer}>
        <form className="form drawer-form" onSubmit={submit}>
          <p className="muted">评论会显示在任务共创区；如果任务已绑定 GitHub issue，会后台同步到 GitHub。</p>
          <MarkdownEditor value={content} onChange={setContent} user={user} openAuth={openAuth} compact fill />
          {error && <Notice type="error" message={error} />}
          <div className="drawer-actions"><button type="button" className="btn" onClick={closeReplyDrawer}>取消</button><button className="btn primary" disabled={submitting || !content.trim()} aria-busy={submitting}>{loadingText(submitting, "发布评论", "发布中...")}</button></div>
        </form>
      </BottomDrawer>
    </>
  );
}

function DocumentsPage({ nav, user, openAuth }) {
  const { documentId } = useParams();
  const navigate = useNavigate();
  const [doc, setDoc] = useState(null);
  const [commentsPage, setCommentsPage] = useState(() => emptyPage());
  const [pagination, setPagination] = useState(defaultPageParams);
  const [docLoading, setDocLoading] = useState(false);
  const [replyDrawerOpen, setReplyDrawerOpen] = useState(false);
  const [replyDrawerHeight, setReplyDrawerHeight] = useState(56);
  const [replyTarget, setReplyTarget] = useState(null);
  const [replyContent, setReplyContent] = useState("");
  const [error, setError] = useState("");
  const notify = useToast();
  const { busy, runBusy } = useBusyActions();
  const liking = doc ? busy(`like-document-${doc.id}`) : false;
  const likedByMe = Boolean(doc?.liked_by_me);
  const submittingComment = doc ? busy(`submit-document-comment-${doc.id}`) : false;

  useEffect(() => {
    if (!documentId && nav.documents?.length) navigate(`/docs/${nav.documents[0].id}`, { replace: true });
  }, [documentId, nav.documents?.length]);

  async function loadDoc() {
    if (!documentId) return;
    setDocLoading(true);
    try {
      setDoc(await request(`/documents/${documentId}`));
      setCommentsPage(await request(`/documents/${documentId}/comments${toQuery(pagination)}`));
    } catch (err) {
      setError(err.message);
    } finally {
      setDocLoading(false);
    }
  }

  useEffect(() => {
    setPagination(defaultPageParams);
    setReplyDrawerOpen(false);
    setReplyTarget(null);
    setReplyContent("");
  }, [documentId]);
  useEffect(() => { loadDoc(); }, [documentId, pagination.page, pagination.page_size]);

  async function like() {
    if (!doc) return;
    await runBusy(`like-document-${doc.id}`, async () => {
      const result = await request(`/documents/${doc.id}/likes`, { method: "POST" });
      setDoc({ ...doc, like_count: result.count, liked_by_me: result.liked });
      notify(result.liked ? "已点赞" : "点赞已更新");
    }).catch((err) => {
      setError(err.message);
      notify("点赞失败", "error");
    });
  }

  function openReplyDrawer(target = null) {
    if (!user) return openAuth();
    setError("");
    setReplyTarget(target);
    setReplyContent("");
    setReplyDrawerOpen(true);
  }

  function closeReplyDrawer() {
    setReplyDrawerOpen(false);
    setReplyTarget(null);
    setReplyContent("");
  }

  async function submitComment(event) {
    event.preventDefault();
    if (!user) return openAuth();
    setError("");
    await runBusy(`submit-document-comment-${doc.id}`, async () => {
      await request(`/documents/${doc.id}/comments`, {
        method: "POST",
        body: JSON.stringify({ content: replyContent, parent_id: replyTarget?.id || undefined }),
      });
      closeReplyDrawer();
      await loadDoc();
      notify(replyTarget ? "回复已发布" : "评论已发布");
    }).catch((err) => setError(err.message));
  }

  if (!doc) {
    return <section className="panel"><div className="empty">暂无文档，管理员可在后台创建。</div></section>;
  }

  return (
    <>
    <section className="doc-layout">
      <article className="panel doc-panel">
        <div className="doc-head"><div><span className="label">文档</span><h2>{doc.title}</h2><p>作者：{doc.author}，更新于 {formatDate(doc.updated_at)}</p></div><div className="row-actions"><button className="btn" disabled={liking || likedByMe} aria-busy={liking} onClick={like}>{loadingText(liking, `${likedByMe ? "已点赞" : "点赞"} ${doc.like_count}`, "处理中...")}</button><button className="btn primary" onClick={() => openReplyDrawer(null)}>回复</button></div></div>
        <div className="markdown-body"><ReactMarkdown {...htmlMarkdownOptions}>{doc.content}</ReactMarkdown></div>
      </article>
      <section className="panel comments-panel document-comments-panel">
        <div className="panel-head"><h2>文档评论</h2><button className="btn" onClick={() => openReplyDrawer(null)}>发起评论</button></div>
        <div className="comment-list compact">
          {docLoading ? <div className="empty">加载中...</div> : pageItems(commentsPage).map((item) => <DocumentComment key={item.id} item={item} onReply={openReplyDrawer} />)}
          {!docLoading && !commentsPage.items.length && <div className="empty">暂无评论</div>}
        </div>
        <Pagination pageData={commentsPage} loading={docLoading} onChange={(next) => setPagination((current) => ({ ...current, ...next }))} />
      </section>
    </section>
    <BottomDrawer title={replyTarget ? "回复评论" : "回复文档"} open={replyDrawerOpen} height={replyDrawerHeight} setHeight={setReplyDrawerHeight} close={closeReplyDrawer}>
      <form className="form drawer-form" onSubmit={submitComment}>
        {replyTarget ? <div className="reply-target"><b>回复 @{replyTarget.user_nickname || replyTarget.user}</b><p>{truncateText(replyTarget.content, 120)}</p></div> : <p className="muted">回复当前文档，内容会显示在文档评论区。</p>}
        <MarkdownEditor value={replyContent} onChange={setReplyContent} user={user} openAuth={openAuth} compact fill />
        {error && <Notice type="error" message={error} />}
        <div className="drawer-actions"><button type="button" className="btn" onClick={closeReplyDrawer}>取消</button><button className="btn primary" disabled={submittingComment || !replyContent.trim()} aria-busy={submittingComment}>{loadingText(submittingComment, replyTarget ? "发布回复" : "发布评论", "发布中...")}</button></div>
      </form>
    </BottomDrawer>
    </>
  );
}

function DocumentComment({ item, onReply }) {
  return (
    <article className={`comment ${item.parent_id ? "is-reply" : ""}`}>
      <div className="comment-head">
        <div><b>{item.user_nickname || item.user}</b><span>{formatDate(item.created_at)}</span></div>
        <button className="link-btn" onClick={() => onReply(item)}>回复</button>
      </div>
      {item.parent_id && <blockquote className="reply-reference">回复 @{item.parent_user_nickname || "原评论"}：{item.parent_content ? truncateText(item.parent_content, 100) : "原评论已删除"}</blockquote>}
      <CommentMarkdown content={item.content} />
      {item.admin_reply && <blockquote>管理员回复：{item.admin_reply}</blockquote>}
    </article>
  );
}

function MinePage({ type, user, openAuth }) {
  const [itemsPage, setItemsPage] = useState(() => emptyPage());
  const [pagination, setPagination] = useState(defaultPageParams);
  const [loading, setLoading] = useState(false);
  const endpoint = type === "tasks" ? "/tasks/my" : "/tasks/sponsor-orders/my";

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    request(`${endpoint}${toQuery(pagination)}`)
      .then(setItemsPage)
      .catch(() => setItemsPage(emptyPage(pagination)))
      .finally(() => setLoading(false));
  }, [type, user?.id, pagination.page, pagination.page_size]);

  useEffect(() => {
    setPagination(defaultPageParams);
  }, [type]);

  if (!user) return <Gate openAuth={openAuth} />;

  return (
    <section className="panel">
      <div className="panel-head"><h2>{type === "tasks" ? "我的需求" : "我的赞助"}</h2></div>
      {loading ? <div className="empty">加载中...</div> : type === "tasks" ? <TaskTable tasks={pageItems(itemsPage)} startIndex={(itemsPage.page - 1) * itemsPage.page_size} onSponsor={() => {}} /> : <OrderList orders={pageItems(itemsPage)} />}
      <Pagination pageData={itemsPage} loading={loading} onChange={(next) => setPagination((current) => ({ ...current, ...next }))} />
    </section>
  );
}

function SettingsPage({ user, openAuth, onUserUpdated }) {
  const [profile, setProfile] = useState({ nickname: user?.nickname || "", avatar_url: user?.avatar_url || "" });
  const [avatarFile, setAvatarFile] = useState(null);
  const [avatarPreview, setAvatarPreview] = useState("");
  const [profileError, setProfileError] = useState("");
  const [passwordForm, setPasswordForm] = useState({ current_password: "", new_password: "", confirm_password: "" });
  const [passwordError, setPasswordError] = useState("");
  const notify = useToast();
  const { busy, runBusy } = useBusyActions();
  const profileSaving = busy("settings-profile");
  const passwordSaving = busy("settings-password");

  useEffect(() => {
    if (!user) return;
    setProfile({ nickname: user.nickname || "", avatar_url: user.avatar_url || "" });
  }, [user?.id, user?.nickname, user?.avatar_url]);

  useEffect(() => {
    if (!avatarFile) {
      setAvatarPreview("");
      return undefined;
    }
    const previewUrl = URL.createObjectURL(avatarFile);
    setAvatarPreview(previewUrl);
    return () => URL.revokeObjectURL(previewUrl);
  }, [avatarFile]);

  if (!user) return <Gate openAuth={openAuth} />;

  async function saveProfile(event) {
    event.preventDefault();
    setProfileError("");
    await runBusy("settings-profile", async () => {
      let avatarUrl = profile.avatar_url || null;
      if (avatarFile) {
        const uploaded = await uploadFile(avatarFile);
        avatarUrl = uploaded.url;
      }
      const updated = await request("/auth/me", { method: "PATCH", body: JSON.stringify({ nickname: profile.nickname, avatar_url: avatarUrl }) });
      onUserUpdated(updated);
      setProfile({ nickname: updated.nickname || "", avatar_url: updated.avatar_url || "" });
      setAvatarFile(null);
      notify("资料已更新");
    }).catch((err) => setProfileError(err.message));
  }

  async function savePassword(event) {
    event.preventDefault();
    setPasswordError("");
    if (passwordForm.new_password !== passwordForm.confirm_password) {
      setPasswordError("两次输入的新密码不一致");
      return;
    }
    await runBusy("settings-password", async () => {
      await request("/auth/password", { method: "PATCH", body: JSON.stringify({ current_password: passwordForm.current_password, new_password: passwordForm.new_password }) });
      setPasswordForm({ current_password: "", new_password: "", confirm_password: "" });
      notify("密码已更新");
    }).catch((err) => setPasswordError(err.message));
  }

  const previewUser = { ...user, nickname: profile.nickname || user.nickname, avatar_url: avatarPreview || profile.avatar_url };

  return (
    <section className="panel settings-page">
      <div className="panel-head">
        <div>
          <h2>账号设置</h2>
          <p>修改头像、昵称和密码。</p>
        </div>
      </div>
      <div className="settings-grid">
        <form className="form settings-card" onSubmit={saveProfile}>
          <h3>个人资料</h3>
          <div className="avatar-editor">
            <UserAvatar user={previewUser} size="lg" />
            <div>
              <label className={`btn ${profileSaving ? "disabled" : ""}`}>选择头像<input type="file" accept="image/*" disabled={profileSaving} onChange={(event) => setAvatarFile(event.target.files?.[0] || null)} /></label>
              <button type="button" className="btn ghost" disabled={profileSaving} onClick={() => { setAvatarFile(null); setProfile((current) => ({ ...current, avatar_url: "" })); }}>移除头像</button>
              <p className="muted">不上传头像时，将显示昵称第一个字。</p>
            </div>
          </div>
          <input placeholder="昵称" value={profile.nickname} onChange={(event) => setProfile({ ...profile, nickname: event.target.value })} />
          {profileError && <Notice type="error" message={profileError} />}
          <button className="btn primary" disabled={profileSaving} aria-busy={profileSaving}>{loadingText(profileSaving, "保存资料", "保存中...")}</button>
        </form>

        <form className="form settings-card" onSubmit={savePassword}>
          <h3>修改密码</h3>
          <input type="password" autoComplete="current-password" placeholder="当前密码" value={passwordForm.current_password} onChange={(event) => setPasswordForm({ ...passwordForm, current_password: event.target.value })} />
          <input type="password" autoComplete="new-password" placeholder="新密码，至少 8 位" value={passwordForm.new_password} onChange={(event) => setPasswordForm({ ...passwordForm, new_password: event.target.value })} />
          <input type="password" autoComplete="new-password" placeholder="再次输入新密码" value={passwordForm.confirm_password} onChange={(event) => setPasswordForm({ ...passwordForm, confirm_password: event.target.value })} />
          {passwordError && <Notice type="error" message={passwordError} />}
          <button className="btn primary" disabled={passwordSaving} aria-busy={passwordSaving}>{loadingText(passwordSaving, "更新密码", "更新中...")}</button>
        </form>
      </div>
    </section>
  );
}

function AdminPage({ user, openAuth, refreshNav }) {
  const location = useLocation();
  const navigate = useNavigate();
  const routeTab = location.pathname === "/admin/folders" ? "folders" : location.pathname === "/admin/documents" ? "documents" : "";
  const [tab, setTab] = useState(routeTab || "tasks");
  const [data, setData] = useState({
    tasks: emptyPage(),
    documents: emptyPage(),
    folders: emptyPage({ page: 1, page_size: 100 }),
    users: emptyPage(),
    comments: emptyPage(),
    orders: emptyPage(),
  });
  const [adminPaging, setAdminPaging] = useState({
    tasks: defaultPageParams,
    documents: defaultPageParams,
    folders: { page: 1, page_size: 100 },
    users: defaultPageParams,
    comments: defaultPageParams,
    orders: defaultPageParams,
  });
  const [adminTaskFilters, setAdminTaskFilters] = useState(createDefaultAdminTaskFilters);
  const [heroContent, setHeroContent] = useState("");
  const [taskForm, setTaskForm] = useState(createDefaultTaskForm);
  const [editingTask, setEditingTask] = useState(null);
  const [taskDrawerOpen, setTaskDrawerOpen] = useState(false);
  const [taskDrawerHeight, setTaskDrawerHeight] = useState(72);
  const [taskDetail, setTaskDetail] = useState(null);
  const [taskDetailComments, setTaskDetailComments] = useState(() => emptyPage());
  const [taskDetailPaging, setTaskDetailPaging] = useState(defaultPageParams);
  const [taskDetailLoading, setTaskDetailLoading] = useState(false);
  const [folderForm, setFolderForm] = useState(createDefaultFolderForm);
  const [editingFolder, setEditingFolder] = useState(null);
  const [folderDrawerOpen, setFolderDrawerOpen] = useState(false);
  const [folderDrawerHeight, setFolderDrawerHeight] = useState(58);
  const [docForm, setDocForm] = useState(createDefaultDocumentForm);
  const [editingDocument, setEditingDocument] = useState(null);
  const [documentDrawerOpen, setDocumentDrawerOpen] = useState(false);
  const [documentDrawerHeight, setDocumentDrawerHeight] = useState(72);
  const [githubSyncResult, setGithubSyncResult] = useState(null);
  const [adminLoading, setAdminLoading] = useState(false);
  const [error, setError] = useState("");
  const notify = useToast();
  const { busy, runBusy } = useBusyActions();
  const activePaging = adminPaging[tab] || defaultPageParams;
  const deferredAdminTaskName = useDeferredValue(adminTaskFilters.name);

  function updateAdminPaging(key, patch) {
    setAdminPaging((current) => ({ ...current, [key]: { ...(current[key] || defaultPageParams), ...patch } }));
  }

  function updateAdminTaskFilters(patch) {
    startTransition(() => setAdminTaskFilters((current) => ({ ...current, ...patch })));
    updateAdminPaging("tasks", { page: 1 });
  }

  function resetAdminTaskFilters() {
    setAdminTaskFilters(createDefaultAdminTaskFilters());
    updateAdminPaging("tasks", { page: 1 });
  }

  function switchAdminTab(nextTab) {
    if (nextTab === "documents") navigate("/admin/documents");
    else if (location.pathname !== "/admin") navigate("/admin");
    setTab(nextTab);
  }

  useEffect(() => {
    if (routeTab) {
      setTab(routeTab);
      return;
    }
    if (location.pathname === "/admin") {
      setTab((current) => (current === "documents" || current === "folders" ? "tasks" : current));
    }
  }, [routeTab, location.pathname]);

  function adminTaskQueryParams() {
    return {
      ...activePaging,
      name: deferredAdminTaskName.trim(),
      status: adminTaskFilters.status.length ? adminTaskFilters.status : undefined,
      sort_by: adminTaskFilters.sort_by,
      sort_order: adminTaskFilters.sort_order,
      source: adminTaskFilters.source.length ? adminTaskFilters.source : undefined,
      visibility: adminTaskFilters.visibility,
      github_sync: adminTaskFilters.github_sync,
    };
  }

  function openTaskDetail(task) {
    setTaskDetail(task);
    setTaskDetailComments(emptyPage());
    setTaskDetailPaging(defaultPageParams);
  }

  function openCreateTaskDrawer() {
    setEditingTask(null);
    setTaskForm(createDefaultTaskForm());
    setTaskDrawerOpen(true);
  }

  function openEditTaskDrawer(task) {
    setEditingTask(task);
    setTaskForm({
      name: task.name || "",
      description: task.description || "",
      start_amount: String(task.start_amount ?? "0"),
      sort_order: task.sort_order == null ? "" : String(task.sort_order),
      status: task.status || "pending_start",
      is_hidden: Boolean(task.is_hidden),
    });
    setTaskDrawerOpen(true);
  }

  function closeTaskDrawer() {
    setTaskDrawerOpen(false);
    setEditingTask(null);
    setTaskForm(createDefaultTaskForm());
  }

  function openCreateDocumentDrawer() {
    setEditingDocument(null);
    setDocForm(createDefaultDocumentForm());
    setDocumentDrawerOpen(true);
  }

  function openEditDocumentDrawer(doc) {
    setEditingDocument(doc);
    setDocForm({
      title: doc.title || "",
      content: doc.content || "",
      folder_id: doc.folder_id == null ? "" : String(doc.folder_id),
      sort_order: doc.sort_order == null ? "" : String(doc.sort_order),
    });
    setDocumentDrawerOpen(true);
  }

  function closeDocumentDrawer() {
    setDocumentDrawerOpen(false);
    setEditingDocument(null);
    setDocForm(createDefaultDocumentForm());
  }

  function openCreateFolderDrawer() {
    setEditingFolder(null);
    setFolderForm(createDefaultFolderForm());
    setFolderDrawerOpen(true);
  }

  function openEditFolderDrawer(folder) {
    setEditingFolder(folder);
    setFolderForm({
      name: folder.name || "",
      parent_id: folder.parent_id == null ? "" : String(folder.parent_id),
      sort_order: folder.sort_order == null ? "" : String(folder.sort_order),
    });
    setFolderDrawerOpen(true);
  }

  function closeFolderDrawer() {
    setFolderDrawerOpen(false);
    setEditingFolder(null);
    setFolderForm(createDefaultFolderForm());
  }

  function replaceTaskLocally(updatedTask) {
    setData((current) => ({
      ...current,
      tasks: {
        ...current.tasks,
        items: pageItems(current.tasks).map((item) => (item.id === updatedTask.id ? updatedTask : item)),
      },
    }));
    setTaskDetail((current) => (current?.id === updatedTask.id ? updatedTask : current));
  }

  async function loadTaskDetail(taskId = taskDetail?.id) {
    if (!taskId) return;
    setTaskDetailLoading(true);
    try {
      const [detail, comments] = await Promise.all([
        request(`/admin/tasks/${taskId}`),
        request(`/admin/tasks/${taskId}/comments${toQuery(taskDetailPaging)}`),
      ]);
      setTaskDetail(detail);
      setTaskDetailComments(comments);
    } catch (err) {
      setError(err.message);
      notify("任务详情加载失败", "error");
    } finally {
      setTaskDetailLoading(false);
    }
  }

  async function load() {
    if (!user || user.role !== "admin") return;
    setAdminLoading(true);
    const next = { ...data };
    try {
      if (tab === "tasks") next.tasks = await request(`/admin/tasks${toQuery(adminTaskQueryParams())}`);
      if (tab === "documents") {
        next.documents = await request(`/admin/documents${toQuery(activePaging)}`);
        next.folders = await request(`/admin/folders${toQuery({ page: 1, page_size: 100 })}`);
      }
      if (tab === "folders") next.folders = await request(`/admin/folders${toQuery(activePaging)}`);
      if (tab === "users") next.users = await request(`/admin/users${toQuery(activePaging)}`);
      if (tab === "comments") next.comments = await request(`/admin/comments${toQuery(activePaging)}`);
      if (tab === "orders") next.orders = await request(`/admin/orders${toQuery(activePaging)}`);
      if (tab === "home") {
        const result = await request("/admin/home-hero");
        setHeroContent(result.content);
      }
      setData(next);
    } finally {
      setAdminLoading(false);
    }
  }

  useEffect(() => { load().catch((err) => setError(err.message)); }, [
    tab,
    user?.id,
    activePaging.page,
    activePaging.page_size,
    deferredAdminTaskName,
    adminTaskFilters.status.join(","),
    adminTaskFilters.sort_by,
    adminTaskFilters.sort_order,
    adminTaskFilters.source.join(","),
    adminTaskFilters.visibility,
    adminTaskFilters.github_sync,
  ]);
  useEffect(() => { if (taskDetail?.id) loadTaskDetail(taskDetail.id); }, [taskDetail?.id, taskDetailPaging.page, taskDetailPaging.page_size]);

  if (!user) return <Gate openAuth={openAuth} />;
  if (user.role !== "admin") return <section className="panel"><div className="empty">需要管理员权限</div></section>;

  async function submitTask(event) {
    event.preventDefault();
    setError("");
    const isEditing = Boolean(editingTask);
    const busyKey = isEditing ? `admin-update-task-${editingTask.id}` : "admin-create-task";
    await runBusy(busyKey, async () => {
      const payload = taskFormPayload(taskForm);
      if (isEditing) {
        const queuesGithubSync = patchQueuesGithubSync(editingTask, payload);
        const updatedTask = await request(`/admin/tasks/${editingTask.id}`, { method: "PUT", body: JSON.stringify(payload) });
        replaceTaskLocally(updatedTask);
        await load();
        notify(queuesGithubSync ? "已保存，GitHub 后台同步中" : "已保存");
      } else {
        await request("/admin/tasks", { method: "POST", body: JSON.stringify(payload) });
        await load();
        notify("任务已创建");
      }
      closeTaskDrawer();
    }).catch((err) => setError(err.message));
  }

  async function updateTask(task, patch) {
    setError("");
    await runBusy(`admin-update-task-${task.id}`, async () => {
      const queuesGithubSync = patchQueuesGithubSync(task, patch);
      const updatedTask = await request(`/admin/tasks/${task.id}`, { method: "PUT", body: JSON.stringify(patch) });
      replaceTaskLocally(updatedTask);
      await load();
      if (taskDetail?.id === task.id) await loadTaskDetail(task.id);
      notify(queuesGithubSync ? "已保存，GitHub 后台同步中" : "已保存");
    }).catch((err) => setError(err.message));
  }

  async function createTaskDetailComment(task, content) {
    setError("");
    await runBusy(`admin-task-detail-comment-${task.id}`, async () => {
      await request(`/admin/tasks/${task.id}/comments`, { method: "POST", body: JSON.stringify({ content }) });
      await loadTaskDetail(task.id);
      await load();
      notify("评论已发布，GitHub 后台同步中");
    });
  }

  async function submitDocument(event) {
    event.preventDefault();
    setError("");
    const isEditing = Boolean(editingDocument);
    const busyKey = isEditing ? `admin-update-document-${editingDocument.id}` : "admin-create-document";
    await runBusy(busyKey, async () => {
      const payload = documentFormPayload(docForm);
      if (isEditing) await request(`/admin/documents/${editingDocument.id}`, { method: "PUT", body: JSON.stringify(payload) });
      else await request("/admin/documents", { method: "POST", body: JSON.stringify(payload) });
      await load();
      await refreshNav();
      notify(isEditing ? "文档已保存" : "文档已创建");
      closeDocumentDrawer();
    }).catch((err) => setError(err.message));
  }

  async function deleteDocument(doc) {
    if (!window.confirm(`确认删除文档“${doc.title}”？`)) return;
    setError("");
    await runBusy(`admin-delete-document-${doc.id}`, async () => {
      await request(`/admin/documents/${doc.id}`, { method: "DELETE" });
      await load();
      await refreshNav();
      notify("文档已删除");
    }).catch((err) => setError(err.message));
  }

  async function submitFolder(event) {
    event.preventDefault();
    setError("");
    const isEditing = Boolean(editingFolder);
    const busyKey = isEditing ? `admin-update-folder-${editingFolder.id}` : "admin-create-folder";
    await runBusy(busyKey, async () => {
      const payload = folderFormPayload(folderForm);
      if (isEditing) await request(`/admin/folders/${editingFolder.id}`, { method: "PUT", body: JSON.stringify(payload) });
      else await request("/admin/folders", { method: "POST", body: JSON.stringify(payload) });
      await load();
      await refreshNav();
      notify(isEditing ? "文件夹已保存" : "文件夹已创建");
      closeFolderDrawer();
    }).catch((err) => setError(err.message));
  }

  async function deleteFolder(folder) {
    if (!window.confirm(`确认删除文件夹“${folder.name}”？`)) return;
    setError("");
    await runBusy(`admin-delete-folder-${folder.id}`, async () => {
      await request(`/admin/folders/${folder.id}`, { method: "DELETE" });
      await load();
      await refreshNav();
      notify("文件夹已删除");
    }).catch((err) => setError(err.message));
  }

  async function commentAction(target, id, action, body) {
    setError("");
    await runBusy(`admin-comment-${target}-${id}-${action}`, async () => {
      const method = action === "delete" ? "DELETE" : "POST";
      await request(`/admin/comments/${target}/${id}${action === "delete" ? "" : `/${action}`}`, { method, body: body ? JSON.stringify(body) : undefined });
      await load();
      notify(action === "delete" && target === "task" ? "评论已删除，GitHub 后台同步中" : { reply: "回复已保存", delete: "评论已删除" }[action] || "操作已保存");
    }).catch((err) => setError(err.message));
  }

  async function saveHeroContent(event) {
    event.preventDefault();
    setError("");
    await runBusy("admin-save-hero", async () => {
      const result = await request("/admin/home-hero", { method: "PUT", body: JSON.stringify({ content: heroContent }) });
      setHeroContent(result.content);
      notify("首页内容已保存");
    }).catch((err) => setError(err.message));
  }

  async function updateUserStatus(item) {
    setError("");
    await runBusy(`admin-user-status-${item.id}`, async () => {
      await request(`/admin/users/${item.id}/${item.is_banned ? "unban" : "ban"}`, { method: "POST" });
      await load();
      notify("用户状态已更新");
    }).catch((err) => setError(err.message));
  }

  async function syncHistoricalIssues() {
    setError("");
    await runBusy("admin-sync-github", async () => {
      const result = await request("/admin/github/sync-issues", { method: "POST" });
      setGithubSyncResult(result);
      await load();
      notify(`GitHub 同步完成：导入 ${result.imported}，跳过 ${result.skipped}，失败 ${result.failed}`);
    }).catch((err) => {
      setError(err.message);
      notify("GitHub 同步失败", "error");
    });
  }

  return (
    <section className="admin-page">
      <div className="admin-tabs">
        {[
          ["tasks", "任务管理"], ["home", "首页 Hero"], ["documents", "文档管理"], ["users", "用户管理"], ["comments", "评论管理"], ["orders", "订单管理"],
        ].map(([key, label]) => <button key={key} className={tab === key ? "active" : ""} disabled={adminLoading} onClick={() => switchAdminTab(key)}>{label}</button>)}
      </div>
      {error && <Notice type="error" message={error} />}
      {tab === "home" && <div className="panel admin-panel">
        <div className="panel-head"><h2>Hero Card 内容编辑</h2></div>
        <form className="form" onSubmit={saveHeroContent}>
          <MarkdownEditor value={heroContent} onChange={setHeroContent} user={user} openAuth={openAuth} allowHtml />
          <button className="btn primary" disabled={busy("admin-save-hero")} aria-busy={busy("admin-save-hero")}>{loadingText(busy("admin-save-hero"), "保存首页内容", "保存中...")}</button>
        </form>
      </div>}
      {tab === "tasks" && <div className="panel admin-panel">
        <div className="panel-head">
          <div><h2>任务管理</h2><p>非 GitHub 来源任务从待审核改为其他状态后，会自动同步到 GitHub issue。</p></div>
          <div className="row-actions">
            <button className="btn primary" onClick={openCreateTaskDrawer}>新增任务</button>
            <button className="btn" disabled={busy("admin-sync-github")} aria-busy={busy("admin-sync-github")} onClick={syncHistoricalIssues}>{loadingText(busy("admin-sync-github"), "同步历史任务", "同步中...")}</button>
          </div>
        </div>
        <AdminTaskFilters filters={adminTaskFilters} loading={adminLoading} updateFilters={updateAdminTaskFilters} resetFilters={resetAdminTaskFilters} />
        {githubSyncResult && <Notice message={`GitHub 历史同步：导入 ${githubSyncResult.imported}，评论 ${githubSyncResult.comments_imported}，跳过 ${githubSyncResult.skipped}，失败 ${githubSyncResult.failed}`} />}
        {adminLoading ? <div className="empty">加载中...</div> : <TaskAdminList tasks={pageItems(data.tasks)} updateTask={updateTask} openDetail={openTaskDetail} openEdit={openEditTaskDrawer} busy={busy} />}
        <Pagination pageData={data.tasks} loading={adminLoading} onChange={(next) => updateAdminPaging("tasks", next)} />
      </div>}
      {tab === "documents" && <div className="panel admin-panel">
        <div className="panel-head">
          <div><h2>文档管理</h2><p>维护文档内容、归属文件夹和展示顺序。</p></div>
          <div className="row-actions">
            <button className="btn primary" onClick={openCreateDocumentDrawer}>创建文档</button>
            <Link className="btn" to="/admin/folders">文件夹管理</Link>
          </div>
        </div>
        {adminLoading ? <div className="empty">加载中...</div> : <DocumentAdminTable documents={pageItems(data.documents)} folders={pageItems(data.folders)} openEdit={openEditDocumentDrawer} deleteDocument={deleteDocument} busy={busy} />}
        <Pagination pageData={data.documents} loading={adminLoading} onChange={(next) => updateAdminPaging("documents", next)} />
      </div>}
      {tab === "folders" && <div className="panel admin-panel">
        <div className="panel-head">
          <div><h2>文件夹管理</h2><p>创建、修改和删除文档文件夹。</p></div>
          <div className="row-actions">
            <button className="btn primary" onClick={openCreateFolderDrawer}>创建文件夹</button>
            <Link className="btn" to="/admin/documents">返回文档管理</Link>
          </div>
        </div>
        {adminLoading ? <div className="empty">加载中...</div> : <FolderAdminTable folders={pageItems(data.folders)} openEdit={openEditFolderDrawer} deleteFolder={deleteFolder} busy={busy} />}
      </div>}
      {tab === "users" && <div className="panel admin-panel"><div className="panel-head"><h2>用户管理</h2></div>{adminLoading ? <div className="empty">加载中...</div> : <div className="admin-list">{pageItems(data.users).map((item) => { const userBusy = busy(`admin-user-status-${item.id}`); return <div key={item.id} className="admin-row"><b>{item.nickname}</b><span>{item.email || item.phone}</span><span>{item.is_banned ? "已封禁" : "正常"}</span><button className="btn" disabled={userBusy} aria-busy={userBusy} onClick={() => updateUserStatus(item)}>{loadingText(userBusy, item.is_banned ? "解封" : "封禁", "处理中...")}</button></div>; })}</div>}<Pagination pageData={data.users} loading={adminLoading} onChange={(next) => updateAdminPaging("users", next)} /></div>}
      {tab === "comments" && <div className="panel admin-panel"><div className="panel-head"><h2>评论管理</h2></div>{adminLoading ? <div className="empty">加载中...</div> : <CommentAdminList comments={pageItems(data.comments)} action={commentAction} busy={busy} />}<Pagination pageData={data.comments} loading={adminLoading} onChange={(next) => updateAdminPaging("comments", next)} /></div>}
      {tab === "orders" && <div className="panel admin-panel"><div className="panel-head"><h2>订单管理</h2></div>{adminLoading ? <div className="empty">加载中...</div> : <OrderList orders={pageItems(data.orders)} />}<Pagination pageData={data.orders} loading={adminLoading} onChange={(next) => updateAdminPaging("orders", next)} /></div>}
      {taskDetail && <TaskDetailModal task={taskDetail} commentsPage={taskDetailComments} loading={taskDetailLoading} user={user} openAuth={openAuth} close={() => setTaskDetail(null)} onEdit={openEditTaskDrawer} onCreateComment={createTaskDetailComment} commentBusy={busy(`admin-task-detail-comment-${taskDetail.id}`)} onPageChange={(next) => setTaskDetailPaging((current) => ({ ...current, ...next }))} />}
      <BottomDrawer title={editingTask ? "编辑任务" : "新增任务"} open={taskDrawerOpen} height={taskDrawerHeight} setHeight={setTaskDrawerHeight} close={closeTaskDrawer}>
        <form className="form drawer-form" onSubmit={submitTask}>
          <div className="inline-form drawer-inline">
            <input placeholder="任务名称" value={taskForm.name} onChange={(event) => setTaskForm({ ...taskForm, name: event.target.value })} />
            <input type="number" placeholder="启动资金" value={taskForm.start_amount} onChange={(event) => setTaskForm({ ...taskForm, start_amount: event.target.value })} />
            <input type="number" placeholder="排序值（留空自动）" value={taskForm.sort_order} onChange={(event) => setTaskForm({ ...taskForm, sort_order: event.target.value })} />
            <select value={taskForm.status} onChange={(event) => setTaskForm({ ...taskForm, status: event.target.value })}>{statusOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
            <label className="drawer-check"><input type="checkbox" checked={taskForm.is_hidden} onChange={(event) => setTaskForm({ ...taskForm, is_hidden: event.target.checked })} />隐藏任务</label>
          </div>
          <MarkdownEditor value={taskForm.description} onChange={(description) => setTaskForm({ ...taskForm, description })} user={user} openAuth={openAuth} fill />
          <div className="drawer-actions"><button type="button" className="btn" onClick={closeTaskDrawer}>取消</button><button className="btn primary" disabled={busy(editingTask ? `admin-update-task-${editingTask.id}` : "admin-create-task")} aria-busy={busy(editingTask ? `admin-update-task-${editingTask.id}` : "admin-create-task")}>{loadingText(busy(editingTask ? `admin-update-task-${editingTask.id}` : "admin-create-task"), editingTask ? "保存任务" : "创建任务", editingTask ? "保存中..." : "创建中...")}</button></div>
        </form>
      </BottomDrawer>
      <BottomDrawer title={editingDocument ? "编辑文档" : "创建文档"} open={documentDrawerOpen} height={documentDrawerHeight} setHeight={setDocumentDrawerHeight} close={closeDocumentDrawer}>
        <form className="form drawer-form" onSubmit={submitDocument}>
          <div className="inline-form drawer-inline">
            <input placeholder="文档标题" value={docForm.title} onChange={(event) => setDocForm({ ...docForm, title: event.target.value })} />
            <select value={docForm.folder_id} onChange={(event) => setDocForm({ ...docForm, folder_id: event.target.value })}>
              <option value="">根目录</option>
              {pageItems(data.folders).map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}
            </select>
            <input type="number" placeholder="排序值（留空自动）" value={docForm.sort_order} onChange={(event) => setDocForm({ ...docForm, sort_order: event.target.value })} />
          </div>
          <MarkdownEditor value={docForm.content} onChange={(content) => setDocForm({ ...docForm, content })} user={user} openAuth={openAuth} fill allowHtml />
          <div className="drawer-actions"><button type="button" className="btn" onClick={closeDocumentDrawer}>取消</button><button className="btn primary" disabled={busy(editingDocument ? `admin-update-document-${editingDocument.id}` : "admin-create-document") || !docForm.title.trim() || !docForm.content.trim()} aria-busy={busy(editingDocument ? `admin-update-document-${editingDocument.id}` : "admin-create-document")}>{loadingText(busy(editingDocument ? `admin-update-document-${editingDocument.id}` : "admin-create-document"), editingDocument ? "保存文档" : "创建文档", editingDocument ? "保存中..." : "创建中...")}</button></div>
        </form>
      </BottomDrawer>
      <BottomDrawer title={editingFolder ? "编辑文件夹" : "创建文件夹"} open={folderDrawerOpen} height={folderDrawerHeight} setHeight={setFolderDrawerHeight} close={closeFolderDrawer}>
        <form className="form drawer-form" onSubmit={submitFolder}>
          <div className="inline-form drawer-inline">
            <input placeholder="文件夹名称" value={folderForm.name} onChange={(event) => setFolderForm({ ...folderForm, name: event.target.value })} />
            <select value={folderForm.parent_id} onChange={(event) => setFolderForm({ ...folderForm, parent_id: event.target.value })}>
              <option value="">根目录</option>
              {pageItems(data.folders).filter((folder) => folder.id !== editingFolder?.id).map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}
            </select>
            <input type="number" placeholder="排序值（留空自动）" value={folderForm.sort_order} onChange={(event) => setFolderForm({ ...folderForm, sort_order: event.target.value })} />
          </div>
          <div className="drawer-actions"><button type="button" className="btn" onClick={closeFolderDrawer}>取消</button><button className="btn primary" disabled={busy(editingFolder ? `admin-update-folder-${editingFolder.id}` : "admin-create-folder") || !folderForm.name.trim()} aria-busy={busy(editingFolder ? `admin-update-folder-${editingFolder.id}` : "admin-create-folder")}>{loadingText(busy(editingFolder ? `admin-update-folder-${editingFolder.id}` : "admin-create-folder"), editingFolder ? "保存文件夹" : "创建文件夹", editingFolder ? "保存中..." : "创建中...")}</button></div>
        </form>
      </BottomDrawer>
    </section>
  );
}

function DocumentAdminTable({ documents, folders, openEdit, deleteDocument, busy }) {
  if (!documents.length) return <div className="empty">暂无文档</div>;
  const folderMap = new Map(folders.map((folder) => [folder.id, folder.name]));
  return (
    <div className="table-scroll">
      <table className="admin-table">
        <thead><tr><th>所在文件夹</th><th>标题</th><th>创建时间</th><th>修改时间</th><th>操作</th></tr></thead>
        <tbody>
          {documents.map((doc) => {
            const deleteBusy = busy(`admin-delete-document-${doc.id}`);
            return (
              <tr key={doc.id}>
                <td>{doc.folder_id ? folderMap.get(doc.folder_id) || "未知文件夹" : "根目录"}</td>
                <td><b>{doc.title}</b></td>
                <td>{formatDate(doc.created_at)}</td>
                <td>{formatDate(doc.updated_at)}</td>
                <td><div className="table-actions"><Link className="link-btn" to={`/docs/${doc.id}`}>查看</Link><button className="link-btn" onClick={() => openEdit(doc)}>修改</button><button className="link-btn danger" disabled={deleteBusy} aria-busy={deleteBusy} onClick={() => deleteDocument(doc)}>{loadingText(deleteBusy, "删除", "处理中...")}</button></div></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function FolderAdminTable({ folders, openEdit, deleteFolder, busy }) {
  if (!folders.length) return <div className="empty">暂无文件夹</div>;
  const folderMap = new Map(folders.map((folder) => [folder.id, folder.name]));
  return (
    <div className="table-scroll">
      <table className="admin-table">
        <thead><tr><th>文件夹名称</th><th>上级文件夹</th><th>排序</th><th>创建时间</th><th>修改时间</th><th>操作</th></tr></thead>
        <tbody>
          {folders.map((folder) => {
            const deleteBusy = busy(`admin-delete-folder-${folder.id}`);
            return (
              <tr key={folder.id}>
                <td><b>{folder.name}</b></td>
                <td>{folder.parent_id ? folderMap.get(folder.parent_id) || "未知文件夹" : "根目录"}</td>
                <td>{folder.sort_order}</td>
                <td>{formatDate(folder.created_at)}</td>
                <td>{formatDate(folder.updated_at)}</td>
                <td><div className="table-actions"><button className="link-btn" onClick={() => openEdit(folder)}>修改</button><button className="link-btn danger" disabled={deleteBusy} aria-busy={deleteBusy} onClick={() => deleteFolder(folder)}>{loadingText(deleteBusy, "删除", "处理中...")}</button></div></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function AdminTaskFilters({ filters, loading, updateFilters, resetFilters }) {
  function toggleArrayValue(key, value, checked) {
    const current = filters[key] || [];
    const next = checked ? [...current, value] : current.filter((item) => item !== value);
    updateFilters({ [key]: next });
  }

  return (
    <div className="admin-task-filters">
      <div className="filters admin-task-filter-row">
        <input
          value={filters.name}
          placeholder="任务名称模糊查询"
          disabled={loading}
          onChange={(event) => updateFilters({ name: event.target.value })}
        />
        <select value={filters.sort_by} disabled={loading} onChange={(event) => updateFilters({ sort_by: event.target.value })}>
          <option value="sort_order">顺序</option>
          <option value="name">名称</option>
          <option value="start_amount">启动资金</option>
          <option value="donated_amount">已赞助金额</option>
        </select>
        <select value={filters.sort_order} disabled={loading} onChange={(event) => updateFilters({ sort_order: event.target.value })}>
          <option value="asc">升序</option>
          <option value="desc">降序</option>
        </select>
        <select value={filters.visibility} disabled={loading} onChange={(event) => updateFilters({ visibility: event.target.value })}>
          {visibilityOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
        <select value={filters.github_sync} disabled={loading} onChange={(event) => updateFilters({ github_sync: event.target.value })}>
          {githubSyncOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
        <button type="button" className="btn" disabled={loading} onClick={resetFilters}>重置</button>
      </div>
      <div className="status-filter admin-task-filter-checks">
        <span className="filter-label">状态</span>
        {statusOptions.map((item) => (
          <label key={item.value}>
            <input
              type="checkbox"
              checked={filters.status.includes(item.value)}
              disabled={loading}
              onChange={(event) => toggleArrayValue("status", item.value, event.target.checked)}
            />
            {item.label}
          </label>
        ))}
      </div>
      <div className="status-filter admin-task-filter-checks">
        <span className="filter-label">来源</span>
        {sourceOptions.map((item) => (
          <label key={item.value}>
            <input
              type="checkbox"
              checked={filters.source.includes(item.value)}
              disabled={loading}
              onChange={(event) => toggleArrayValue("source", item.value, event.target.checked)}
            />
            {item.label}
          </label>
        ))}
      </div>
    </div>
  );
}

function TaskAdminList({ tasks, updateTask, openDetail, openEdit, busy }) {
  return (
    <div className="admin-list">
      {tasks.map((task) => {
        const taskBusy = busy(`admin-update-task-${task.id}`);
        return (
          <div key={task.id} className="admin-row task-admin">
            <button type="button" className="task-title-btn" onClick={() => openDetail(task)}><b>{task.sort_order}. {task.name}</b></button>
            <span className="source-chip">{sourceLabel(task.source)}</span>
            <span>{task.github_issue_url ? <a href={task.github_issue_url} target="_blank" rel="noreferrer">Issue #{task.github_issue_number}</a> : "未同步"}</span>
            <span className={taskGithubSyncClass(task)} title={taskGithubSyncTitle(task)}>{taskGithubSyncLabel(task)}</span>
            <span>¥{task.start_amount} / ¥{task.donated_amount}</span>
            <button className="btn" disabled={taskBusy} aria-busy={taskBusy} onClick={() => openEdit(task)}>编辑</button>
            <button className="btn" disabled={taskBusy} aria-busy={taskBusy} onClick={() => updateTask(task, { is_hidden: !task.is_hidden })}>{loadingText(taskBusy, task.is_hidden ? "取消隐藏" : "隐藏", "保存中...")}</button>
            <select value={task.status} disabled={taskBusy} aria-busy={taskBusy} onChange={(event) => updateTask(task, { status: event.target.value })}>{statusOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
          </div>
        );
      })}
    </div>
  );
}

function TaskDetailModal({ task, commentsPage, loading, user, openAuth, close, onEdit, onCreateComment, commentBusy, onPageChange }) {
  const comments = pageItems(commentsPage);
  const [commentContent, setCommentContent] = useState("");
  const [commentError, setCommentError] = useState("");

  async function submitComment(event) {
    event.preventDefault();
    const content = commentContent.trim();
    if (!content) {
      setCommentError("请输入评论内容");
      return;
    }
    setCommentError("");
    try {
      await onCreateComment(task, content);
      setCommentContent("");
    } catch (err) {
      setCommentError(err.message);
    }
  }

  return (
    <Modal title={`任务详情：${task.name}`} close={close} actions={<button onClick={() => onEdit(task)}>编辑</button>} wide>
      <div className="task-detail">
        <div className="task-detail-grid">
          <DetailItem label="状态" value={task.status_label} />
          <DetailItem label="来源" value={sourceLabel(task.source)} />
          <DetailItem label="可见性" value={task.is_hidden ? "已隐藏" : "公开"} />
          <DetailItem label="排序" value={task.sort_order} />
          <DetailItem label="资金" value={`¥${task.start_amount} / ¥${task.donated_amount}`} />
          <DetailItem label="共创人数" value={task.co_creator_count} />
          <DetailItem label="创建时间" value={formatDate(task.created_at)} />
          <DetailItem label="更新时间" value={formatDate(task.updated_at)} />
          <DetailItem label="GitHub" value={task.github_issue_url ? <a href={task.github_issue_url} target="_blank" rel="noreferrer">Issue #{task.github_issue_number}</a> : "未同步"} />
          <DetailItem label="同步状态" value={<span className={taskGithubSyncClass(task)} title={taskGithubSyncTitle(task)}>{taskGithubSyncLabel(task)}</span>} />
        </div>
        {task.github_sync_error && <Notice type="error" message={task.github_sync_error} />}
        <section className="task-detail-section">
          <h3>任务描述</h3>
          <div className="task-detail-markdown markdown-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{task.description || "暂无描述"}</ReactMarkdown>
          </div>
        </section>
        <section className="task-detail-section">
          <h3>评论</h3>
          {loading ? <div className="empty">加载评论中...</div> : (
            <div className="task-detail-comments">
              {comments.map((item) => <TaskDetailComment key={item.id} item={item} />)}
              {!comments.length && <div className="empty">暂无评论</div>}
            </div>
          )}
          <Pagination pageData={commentsPage} loading={loading} onChange={onPageChange} />
          <form className="form" onSubmit={submitComment}>
            <MarkdownEditor value={commentContent} onChange={setCommentContent} user={user} openAuth={openAuth} compact />
            {commentError && <Notice type="error" message={commentError} />}
            <button className="btn primary" disabled={commentBusy || !commentContent.trim()} aria-busy={commentBusy}>{loadingText(commentBusy, "发布管理员评论", "发布中...")}</button>
          </form>
        </section>
      </div>
    </Modal>
  );
}

function DetailItem({ label, value }) {
  return <div className="detail-item"><span>{label}</span><b>{value}</b></div>;
}

function TaskDetailComment({ item }) {
  return (
    <article className="detail-comment">
      <div className="detail-comment-head">
        <div><b>{item.user_nickname || item.user || "未知用户"}</b><span>{formatDate(item.created_at)}</span></div>
        {item.github_comment_id && <span className="source-chip">GitHub #{item.github_comment_id}</span>}
      </div>
      <div className="detail-comment-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.content || "暂无内容"}</ReactMarkdown>
      </div>
      {item.admin_reply && <blockquote>管理员回复：{item.admin_reply}</blockquote>}
      {item.github_sync_error && <Notice type="error" message={item.github_sync_error} />}
    </article>
  );
}

function sourceLabel(source) {
  if (source === "github") return "GitHub";
  if (source === "user") return "用户需求";
  return "管理员";
}

function taskGithubSyncStatus(task) {
  if (task.github_sync_status) return task.github_sync_status;
  if (task.github_sync_error) return "error";
  if (!task.github_issue_number) return "unbound";
  return task.last_github_sync_at ? "synced" : "pending";
}

function taskGithubSyncLabel(task) {
  if (task.github_sync_status_label) return task.github_sync_status_label;
  return {
    unbound: "未同步",
    pending: "待同步",
    synced: "已同步",
    error: "同步失败",
  }[taskGithubSyncStatus(task)] || "待同步";
}

function taskGithubSyncClass(task) {
  const status = taskGithubSyncStatus(task);
  if (status === "error") return "sync-error";
  if (status === "synced") return "sync-ok";
  return "sync-pending";
}

function taskGithubSyncTitle(task) {
  if (task.github_sync_error) return task.github_sync_error;
  return task.last_github_sync_at ? `最后同步：${formatDate(task.last_github_sync_at)}` : "";
}

function patchQueuesGithubSync(task, patch) {
  const fields = Object.keys(patch).filter((field) => taskPatchValueChanged(task, field, patch[field]));
  const nextStatus = patch.status ?? task.status;
  const movedOutOfReview = fields.includes("status") && task.status === "pending_review" && nextStatus !== "pending_review";
  if (movedOutOfReview && task.source !== "github" && !task.github_issue_number) return true;
  return Boolean(task.github_issue_number && fields.some((field) => ["name", "description", "status"].includes(field)));
}

function taskPatchValueChanged(task, field, value) {
  if (value === undefined) return false;
  if (["name", "description", "status"].includes(field)) return String(task[field] ?? "") !== String(value ?? "");
  return task[field] !== value;
}

function CommentAdminList({ comments, action, busy }) {
  const all = comments.map((item) => ({ ...item, label: `${item.target === "task" ? "任务" : "文档"} #${item.target_id}` }));
  return <div className="admin-list">{all.map((item) => {
    const replyBusy = busy(`admin-comment-${item.target}-${item.id}-reply`);
    const deleteBusy = busy(`admin-comment-${item.target}-${item.id}-delete`);
    return <div key={`${item.target}-${item.id}`} className="admin-row comment-admin"><b>{item.label}</b><span>{item.user}</span><p>{item.content}</p><button className="btn" disabled={replyBusy} aria-busy={replyBusy} onClick={() => { if (busy(`admin-comment-${item.target}-${item.id}-reply`)) return; const admin_reply = prompt("回复内容", item.admin_reply || ""); if (admin_reply === null) return; action(item.target, item.id, "reply", { admin_reply }); }}>{loadingText(replyBusy, "回复", "保存中...")}</button><button className="btn danger" disabled={deleteBusy} aria-busy={deleteBusy} onClick={() => action(item.target, item.id, "delete")}>{loadingText(deleteBusy, "删除", "处理中...")}</button></div>;
  })}</div>;
}

function OrderList({ orders }) {
  if (!orders.length) return <div className="empty">暂无订单</div>;
  return <div className="admin-list">{orders.map((order) => {
    const providerOrderNo = order.xorpay_aoid || order.afdian_order_no || "-";
    return <div key={order.id} className="admin-row"><b>{order.merchant_order_no}</b><span>{order.task_id ? `任务 #${order.task_id}` : "赞助作者"}</span><span>{order.channel}</span><span>{providerOrderNo}</span><span>¥{order.amount}</span><span>{order.status}</span><span>{formatDate(order.created_at)}</span></div>;
  })}</div>;
}

function Pagination({ pageData, onChange, loading = false }) {
  const page = pageData?.page || 1;
  const pageSize = pageData?.page_size || 20;
  const pages = pageData?.pages || 1;
  const total = pageData?.total || 0;
  if (!pageData) return null;
  return (
    <div className="pagination">
      <span>共 {total} 条，第 {page} / {pages} 页</span>
      <div className="pagination-actions">
        <button className="btn" disabled={loading || page <= 1} aria-busy={loading} onClick={() => onChange({ page: 1 })}>首页</button>
        <button className="btn" disabled={loading || page <= 1} aria-busy={loading} onClick={() => onChange({ page: page - 1 })}>上一页</button>
        <button className="btn" disabled={loading || page >= pages} aria-busy={loading} onClick={() => onChange({ page: page + 1 })}>下一页</button>
        <button className="btn" disabled={loading || page >= pages} aria-busy={loading} onClick={() => onChange({ page: pages })}>末页</button>
        <select value={pageSize} disabled={loading} aria-busy={loading} onChange={(event) => onChange({ page: 1, page_size: Number(event.target.value) })}>
          {pageSizeOptions.map((size) => <option key={size} value={size}>{size} 条/页</option>)}
        </select>
      </div>
    </div>
  );
}

function BottomDrawer({ title, open, height, setHeight, close, children }) {
  const dragRef = useRef(null);
  const drawerRef = useRef(null);
  const handleKeyDown = useOverlayFocus(drawerRef, close, open);
  if (!open) return null;

  function startDrag(event) {
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = height;
    function move(moveEvent) {
      const delta = ((startY - moveEvent.clientY) / window.innerHeight) * 100;
      setHeight(Math.min(92, Math.max(42, startHeight + delta)));
    }
    function stop() {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    }
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  }

  return (
    <div className="drawer-backdrop" onClick={close}>
      <section
        className="bottom-drawer"
        ref={drawerRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        style={{ height: `${height}vh` }}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <div className="drawer-handle" ref={dragRef} onPointerDown={startDrag} />
        <div className="drawer-head"><h2>{title}</h2><button onClick={close}>关闭</button></div>
        <div className="drawer-body">{children}</div>
      </section>
    </div>
  );
}

function MarkdownEditor({ value, onChange, user, openAuth, compact = false, fill = false, allowHtml = false }) {
  const [uploading, setUploading] = useState(false);
  const editorRef = useRef(null);
  const selectionRef = useRef(null);
  const valueRef = useRef(value || "");
  const notify = useToast();

  useEffect(() => {
    valueRef.current = value || "";
  }, [value]);

  function updateValue(next) {
    valueRef.current = next;
    onChange(next);
  }

  function ensureCanUpload() {
    if (user) return true;
    notify("请先登录后上传文件", "info");
    openAuth?.();
    return false;
  }

  function fileToMarkdown(uploaded) {
    const filename = cleanFilename(uploaded.original_filename);
    const isImage = uploaded.mime_type.startsWith("image/");
    return isImage ? `![${filename}](${uploaded.url})` : `[${filename}](${uploaded.url})`;
  }

  function cleanFilename(filename) {
    return (filename || "upload").replace(/[\[\]\r\n]/g, "");
  }

  function createUploadPlaceholder(file, index) {
    const id = `upload-${Date.now()}-${index}-${Math.random().toString(36).slice(2)}`;
    const filename = cleanFilename(file.name || `附件${index + 1}`);
    return {
      id,
      file,
      filename,
      markdown: `<!-- ${id} -->\n> 正在上传：${filename}...\n<!-- /${id} -->`,
    };
  }

  function replaceUploadPlaceholder(id, markdown) {
    const text = valueRef.current || "";
    const pattern = new RegExp(`<!-- ${escapeRegExp(id)} -->[\\s\\S]*?<!-- /${escapeRegExp(id)} -->`);
    if (!pattern.test(text)) return;
    updateValue(text.replace(pattern, markdown));
  }

  function escapeRegExp(text) {
    return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function insertMarkdown(markdown, selection) {
    const text = valueRef.current || "";
    const start = selection?.start ?? text.length;
    const end = selection?.end ?? text.length;
    const before = text.slice(0, start);
    const after = text.slice(end);
    const prefix = before && !before.endsWith("\n") ? "\n" : "";
    const suffix = after && !after.startsWith("\n") ? "\n" : "";
    const inserted = `${prefix}${markdown}${suffix}`;
    updateValue(`${before}${inserted}${after}`);
    window.requestAnimationFrame(() => {
      const textarea = editorRef.current?.querySelector("textarea");
      if (!textarea) return;
      const cursor = start + inserted.length;
      selectionRef.current = { start: cursor, end: cursor };
      textarea.focus();
      textarea.setSelectionRange(cursor, cursor);
    });
  }

  async function uploadFiles(files, selection) {
    if (uploading) return;
    const list = Array.from(files || []).filter(Boolean);
    if (!list.length || !ensureCanUpload()) return;
    const placeholders = list.map(createUploadPlaceholder);
    insertMarkdown(placeholders.map((item) => item.markdown).join("\n\n"), selection);
    setUploading(true);
    let uploadedCount = 0;
    try {
      for (const item of placeholders) {
        try {
          const uploaded = await uploadFile(item.file);
          replaceUploadPlaceholder(item.id, fileToMarkdown(uploaded));
          uploadedCount += 1;
        } catch (err) {
          replaceUploadPlaceholder(item.id, `> 上传失败：${item.filename}，请重试`);
          notify(`${item.filename} 上传失败`, "error");
        }
      }
      if (uploadedCount) notify(uploadedCount > 1 ? `${uploadedCount} 个附件已上传` : "附件已上传");
    } finally {
      setUploading(false);
    }
  }

  async function onFile(event) {
    await uploadFiles(event.target.files, selectionRef.current);
    event.target.value = "";
  }

  function rememberSelection(event) {
    selectionRef.current = { start: event.currentTarget.selectionStart, end: event.currentTarget.selectionEnd };
  }

  function onPaste(event) {
    const files = Array.from(event.clipboardData?.files || []);
    if (!files.length) return;
    event.preventDefault();
    uploadFiles(files, { start: event.currentTarget.selectionStart, end: event.currentTarget.selectionEnd });
  }

  return (
    <div className={`markdown-editor ${compact ? "compact" : ""} ${fill ? "fill" : ""}`} data-color-mode="light" ref={editorRef}>
      <div className="editor-uploadbar">
        <span>支持 Markdown，可粘贴图片或文件自动上传</span>
        <label className={`file-btn ${uploading ? "disabled" : ""}`} aria-busy={uploading}>{uploading ? "上传中..." : "上传附件"}<input type="file" multiple disabled={uploading} onChange={onFile} /></label>
      </div>
      <MDEditor
        value={value}
        onChange={(next) => updateValue(next || "")}
        preview="live"
        height={compact ? 280 : 360}
        commands={[
          commands.bold,
          commands.italic,
          commands.strikethrough,
          commands.divider,
          commands.group([commands.title1, commands.title2, commands.title3], { name: "title", groupName: "title", buttonProps: { "aria-label": "插入标题" } }),
          commands.divider,
          commands.link,
          commands.quote,
          commands.code,
          commands.codeBlock,
          commands.table,
          commands.divider,
          commands.unorderedListCommand,
          commands.orderedListCommand,
          commands.checkedListCommand,
        ]}
        extraCommands={[commands.codeEdit, commands.codeLive, commands.codePreview, commands.fullscreen]}
        previewOptions={{ remarkPlugins: [remarkGfm], ...(allowHtml ? { rehypePlugins: [rehypeRaw] } : {}) }}
        textareaProps={{ placeholder: "输入 Markdown，或直接粘贴图片/文件上传", onPaste, onSelect: rememberSelection, onClick: rememberSelection, onKeyUp: rememberSelection }}
      />
    </div>
  );
}

function AuthModal({ close, onAuthed }) {
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ account: "", password: "", nickname: "", code: "", new_password: "" });
  const [avatarFile, setAvatarFile] = useState(null);
  const [avatarPreview, setAvatarPreview] = useState("");
  const [error, setError] = useState("");
  const notify = useToast();
  const { busy, runBusy } = useBusyActions();
  const authSubmitting = busy("auth-submit");
  const codeSending = busy(`auth-code-${mode}`);

  useEffect(() => {
    if (!avatarFile) {
      setAvatarPreview("");
      return undefined;
    }
    const previewUrl = URL.createObjectURL(avatarFile);
    setAvatarPreview(previewUrl);
    return () => URL.revokeObjectURL(previewUrl);
  }, [avatarFile]);

  async function sendCode(purpose) {
    setError("");
    await runBusy(`auth-code-${purpose}`, async () => {
      await request("/auth/send-code", { method: "POST", body: JSON.stringify({ target: form.account, purpose }) });
      notify("验证码已发送");
    }).catch((err) => setError(err.message));
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    await runBusy("auth-submit", async () => {
      if (mode === "login") {
        const result = await request("/auth/login", { method: "POST", body: JSON.stringify({ account: form.account, password: form.password }) });
        setToken(result.access_token);
      }
      if (mode === "register") {
        const payload = form.account.includes("@") ? { email: form.account } : { phone: form.account };
        const result = await request("/auth/register", { method: "POST", body: JSON.stringify({ ...payload, nickname: form.nickname, password: form.password, code: form.code }) });
        setToken(result.access_token);
        if (avatarFile) {
          try {
            const uploaded = await uploadFile(avatarFile);
            await request("/auth/me", { method: "PATCH", body: JSON.stringify({ avatar_url: uploaded.url }) });
          } catch {
            notify("注册成功，头像上传失败，可稍后在设置页修改", "error");
          }
        }
      }
      if (mode === "reset") {
        await request("/auth/reset-password", { method: "POST", body: JSON.stringify({ account: form.account, code: form.code, new_password: form.new_password }) });
        setMode("login");
        notify("密码已重置");
        return;
      }
      await onAuthed();
      notify(mode === "register" ? "注册成功" : "登录成功");
      close();
    }).catch((err) => setError(err.message));
  }

  const registerPreviewUser = { nickname: form.nickname || "用户", avatar_url: avatarPreview };

  return (
    <Modal title={mode === "login" ? "登录" : mode === "register" ? "注册" : "忘记密码"} close={close}>
      <div className="auth-tabs"><button className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>登录</button><button className={mode === "register" ? "active" : ""} onClick={() => setMode("register")}>注册</button><button className={mode === "reset" ? "active" : ""} onClick={() => setMode("reset")}>忘记密码</button></div>
      <form className="form" onSubmit={submit}>
        <input placeholder="邮箱或手机号" value={form.account} onChange={(event) => setForm({ ...form, account: event.target.value })} />
        {mode === "register" && <input placeholder="昵称" value={form.nickname} onChange={(event) => setForm({ ...form, nickname: event.target.value })} />}
        {mode === "register" && (
          <div className="avatar-field">
            <UserAvatar user={registerPreviewUser} size="md" />
            <div>
              <label className={`btn ${authSubmitting ? "disabled" : ""}`}>选择头像<input type="file" accept="image/*" disabled={authSubmitting} onChange={(event) => setAvatarFile(event.target.files?.[0] || null)} /></label>
              <p className="muted">可选，不上传则显示昵称首字。</p>
            </div>
          </div>
        )}
        {mode !== "reset" && <input type="password" placeholder="密码，至少 8 位" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} />}
        {mode !== "login" && <div className="code-row"><input placeholder="验证码" value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value })} /><button type="button" className="btn" disabled={codeSending} aria-busy={codeSending} onClick={() => sendCode(mode === "register" ? "register" : "reset")}>{loadingText(codeSending, "发送验证码", "发送中...")}</button></div>}
        {mode === "reset" && <input type="password" placeholder="新密码" value={form.new_password} onChange={(event) => setForm({ ...form, new_password: event.target.value })} />}
        {mode === "register" && <p className="muted">仅支持密码登录，请牢记密码。</p>}
        {error && <Notice type="error" message={error} />}
        <button className="btn primary" disabled={authSubmitting} aria-busy={authSubmitting}>{loadingText(authSubmitting, mode === "login" ? "登录" : mode === "register" ? "注册" : "重置密码", mode === "login" ? "登录中..." : mode === "register" ? "注册中..." : "处理中...")}</button>
      </form>
    </Modal>
  );
}

function Comment({ item }) {
  return <article className="comment"><b>{item.user_nickname || item.user}</b><span>{formatDate(item.created_at)}</span><CommentMarkdown content={item.content} />{item.admin_reply && <blockquote>管理员回复：{item.admin_reply}</blockquote>}</article>;
}

function CommentMarkdown({ content }) {
  return <div className="comment-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{content || ""}</ReactMarkdown></div>;
}

function Gate({ openAuth }) {
  return <section className="panel"><div className="empty">需要登录后查看。<button className="btn primary" onClick={openAuth}>立即登录</button></div></section>;
}

function Modal({ title, close, children, wide = false, actions = null }) {
  const modalRef = useRef(null);
  const handleKeyDown = useOverlayFocus(modalRef, close);
  return (
    <div className="modal-backdrop">
      <div
        className={`modal ${wide ? "wide" : ""}`}
        ref={modalRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onKeyDown={handleKeyDown}
      >
        <div className="modal-head"><h2>{title}</h2><div className="row-actions">{actions}<button onClick={close}>关闭</button></div></div>
        {children}
      </div>
    </div>
  );
}

function Notice({ message, type = "info" }) {
  return <div className={`notice ${type}`}>{message}</div>;
}

function formatDate(value) {
  if (!value) return "-";
  return new Date(value).toLocaleDateString("zh-CN");
}

function formatMoney(value) {
  return `¥${Number(value || 0).toFixed(2)}`;
}

function truncateText(value, maxLength) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}...`;
}
