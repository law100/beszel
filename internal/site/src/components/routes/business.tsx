import { useCallback, useEffect, useRef, useState, type ReactNode } from "react"
import {
	AlertCircleIcon,
	ArrowDownUpIcon,
	ArrowUpRightIcon,
	CheckCircle2Icon,
	ClockIcon,
	CloudIcon,
	DatabaseBackupIcon,
	FolderIcon,
	HardDriveIcon,
	LoaderCircleIcon,
	RefreshCwIcon,
	ShieldCheckIcon,
} from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { prependBasePath } from "@/components/router"

type Task = {
	id: string
	label: string
	status: string
	createdAt: number | null
	updatedAt: number | null
	totalFiles: number | null
	totalBytes: number | null
	completedFiles: number | null
	completedBytes: number | null
	percent: number | null
	issue: string | null
	currentFile: { name: string } | null
	downloadBytesPerSecond: number | null
	uploadBytesPerSecond: number | null
	etaSeconds: number | null
	elapsedSeconds: number
	averageBytesPerSecond: number | null
}
type Account = {
	id: string
	name: string
	totalBytes: number | null
	usedBytes: number | null
	remainingBytes: number | null
	scannedAt: number | null
	usageState: string
	usageStale: boolean
	authorization: string
	validatedAt: number | null
	expiresAt: number | null
}
type Overview = {
	generatedAt: number
	accounts: Account[] | null
	tasks: Task[] | null
	library: {
		fileCount: number
		totalBytes: number
		shareCount: number
		recent: {
			label: string
			status: string
			fileCount: number | null
			totalBytes: number | null
			updatedAt: number | null
		}[]
	} | null
	maintenance: {
		backup: {
			completedAt: number
			sizeBytes: number | null
			verified: boolean
			state: string
			offServer: boolean
		} | null
		certificates: { domain: string; daysRemaining: number | null; expiresAt: number | null }[]
	} | null
	issues: { severity: string; title: string; area: string }[]
}

const stateNames: Record<string, string> = {
	queued: "排队中",
	preparing: "准备中",
	saving: "来源转存中",
	downloading: "下载中",
	uploading: "上传中",
	checking: "核对中",
	confirming: "确认上传结果",
	source_waiting: "等待来源恢复",
	resting: "计划休息中",
	paused: "已暂停",
	needs_attention: "需要处理",
	complete: "已完成",
	cancelled: "已取消",
}
const activeStates = new Set([
	"queued",
	"preparing",
	"saving",
	"downloading",
	"uploading",
	"checking",
	"confirming",
	"source_waiting",
	"resting",
])
const bytes = (n: number | null | undefined) => {
	if (n == null || !Number.isFinite(n)) return "—"
	if (n === 0) return "0 B"
	const units = ["B", "KiB", "MiB", "GiB", "TiB"]
	const i = Math.min(4, Math.max(0, Math.floor(Math.log(n) / Math.log(1024))))
	return `${(n / 1024 ** i).toLocaleString("zh-CN", { maximumFractionDigits: i >= 4 ? 2 : i ? 1 : 0 })} ${units[i]}`
}
const count = (n: number | null | undefined) => (n == null ? "—" : n.toLocaleString("zh-CN"))
const date = (n: number | null | undefined) =>
	n == null
		? "暂无数据"
		: new Date(n * 1000).toLocaleString("zh-CN", {
				month: "2-digit",
				day: "2-digit",
				hour: "2-digit",
				minute: "2-digit",
				hour12: false,
			})
const duration = (n: number | null | undefined) => {
	if (n == null) return "—"
	if (n < 60) return `${Math.round(n)} 秒`
	if (n < 3600) return `${Math.round(n / 60)} 分钟`
	if (n < 86400) return `${(n / 3600).toFixed(1)} 小时`
	return `${(n / 86400).toFixed(1)} 天`
}

function Badge({ children, warning = false }: { children: ReactNode; warning?: boolean }) {
	return (
		<span
			className={cn(
				"inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
				warning
					? "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300"
					: "border-border bg-muted/40 text-muted-foreground"
			)}
		>
			{children}
		</span>
	)
}
function Empty({ children }: { children: ReactNode }) {
	return (
		<div className="flex min-h-28 items-center justify-center rounded-md border border-dashed px-5 py-8 text-center text-sm text-muted-foreground">
			{children}
		</div>
	)
}
function Metric({ label, value, detail, icon }: { label: string; value: string; detail: string; icon: ReactNode }) {
	return (
		<Card className="min-w-0 shadow-none">
			<CardContent className="p-4 sm:p-5">
				<div className="flex items-center justify-between gap-2 text-xs text-muted-foreground sm:text-sm">
					<span>{label}</span>
					{icon}
				</div>
				<div className="mt-4 break-words text-2xl font-semibold tracking-tight tabular-nums sm:text-3xl">{value}</div>
				<p className="mt-2 text-xs text-muted-foreground">{detail}</p>
			</CardContent>
		</Card>
	)
}
function Meter({ value }: { value: number | null }) {
	return (
		<div
			className="h-1.5 overflow-hidden rounded-full bg-muted"
			role="progressbar"
			aria-label="完成进度"
			aria-valuenow={value ?? undefined}
			aria-valuemin={0}
			aria-valuemax={100}
		>
			<div
				className="h-full rounded-full bg-primary transition-[width] duration-500 motion-reduce:transition-none"
				style={{ width: `${Math.max(0, Math.min(100, value ?? 0))}%` }}
			/>
		</div>
	)
}

export default function Business() {
	const [data, setData] = useState<Overview | null>(null)
	const [error, setError] = useState<string | null>(null)
	const [loading, setLoading] = useState(true)
	const controller = useRef<AbortController | null>(null)
	const refresh = useCallback(async () => {
		if (controller.current) return
		const abort = new AbortController()
		controller.current = abort
		setLoading(true)
		const timeout = setTimeout(() => abort.abort(), 8000)
		try {
			const response = await fetch(prependBasePath("/api/law100/overview"), {
				credentials: "same-origin",
				cache: "no-store",
				signal: abort.signal,
			})
			if (response.status === 401 || response.status === 403) throw new Error("会话已失效或没有访问权限，请重新登录。")
			if (!response.ok) throw new Error("暂时无法获取业务数据，请稍后刷新。")
			const result = (await response.json()) as Overview
			if (typeof result.generatedAt !== "number" || !Array.isArray(result.issues)) throw new Error("业务数据暂不可用。")
			setData(result)
			setError(null)
		} catch (e) {
			setError(e instanceof Error && e.name !== "AbortError" ? e.message : "请求超时，保留上次数据。")
		} finally {
			clearTimeout(timeout)
			controller.current = null
			setLoading(false)
		}
	}, [])
	useEffect(() => {
		document.title = "业务概览 / Beszel"
		void refresh()
		const interval = setInterval(() => {
			if (!document.hidden) void refresh()
		}, 15000)
		const onVisible = () => {
			if (!document.hidden) void refresh()
		}
		document.addEventListener("visibilitychange", onVisible)
		return () => {
			clearInterval(interval)
			document.removeEventListener("visibilitychange", onVisible)
			controller.current?.abort()
		}
	}, [refresh])
	const tasks = data?.tasks
	const current =
		tasks?.find((t) => activeStates.has(t.status)) ??
		tasks?.find((t) => t.status === "needs_attention") ??
		tasks?.find((t) => t.status === "paused")
	const accounts = data?.accounts
	const capacityKnown = !!accounts?.length && accounts.every((a) => a.remainingBytes != null)
	const remaining = capacityKnown ? accounts.reduce((sum, a) => sum + (a.remainingBytes ?? 0), 0) : null
	const stale = !!data && Date.now() / 1000 - data.generatedAt > 90
	const history = tasks?.filter((t) => t.status === "complete" || t.status === "cancelled").slice(0, 6)
	return (
		<div className="space-y-5 pb-8">
			<header className="flex flex-wrap items-start justify-between gap-4 py-1">
				<div>
					<div className="flex items-center gap-3">
						<h1 className="text-2xl font-semibold tracking-tight">业务概览</h1>
						<Badge>只读</Badge>
					</div>
					<p className="mt-2 text-sm text-muted-foreground">容量、资料导入与维护状态。</p>
				</div>
				<div className="flex items-center gap-3">
					<span className="text-xs text-muted-foreground tabular-nums">
						{data ? `更新于 ${date(data.generatedAt)}` : "正在获取数据"}
					</span>
					<Button variant="outline" size="sm" disabled={loading} onClick={() => void refresh()}>
						<RefreshCwIcon className={cn("me-2 h-3.5 w-3.5", loading && "animate-spin motion-reduce:animate-none")} />
						刷新
					</Button>
				</div>
			</header>
			{(error || stale) && (
				<div
					role="alert"
					className="flex flex-wrap items-center gap-3 rounded-md border border-amber-500/25 bg-amber-500/5 p-4 text-sm"
				>
					<AlertCircleIcon className="h-4 w-4 shrink-0" />
					<span>{error ?? "数据采集暂未更新，以下为上次记录。"}</span>
					{error?.includes("登录") && (
						<a href={prependBasePath("/_auth/login?return=/business")} className="underline underline-offset-4">
							重新登录
						</a>
					)}
				</div>
			)}
			{loading && !data ? (
				<div className="flex min-h-64 items-center justify-center gap-3 text-muted-foreground" role="status">
					<LoaderCircleIcon className="h-5 w-5 animate-spin motion-reduce:animate-none" />
					正在加载业务概览…
				</div>
			) : (
				<>
					<div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
						<Metric
							label="网盘剩余容量"
							value={bytes(remaining)}
							detail={capacityKnown ? `${accounts.length} 个账户 · 配置容量 / 缓存统计` : "等待完整容量统计"}
							icon={<CloudIcon className="h-4 w-4" />}
						/>
						<Metric
							label="资料总量"
							value={bytes(data?.library?.totalBytes)}
							detail={data?.library ? `${count(data.library.fileCount)} 个文件 · 导入记录口径` : "暂无资料库数据"}
							icon={<FolderIcon className="h-4 w-4" />}
						/>
						<Metric
							label="当前导入进度"
							value={current?.percent != null ? `${current.percent.toFixed(1)}%` : current ? "—" : tasks ? "空闲" : "—"}
							detail={
								current
									? `${stateNames[current.status] ?? "状态未知"} · ${count(current.completedFiles)} / ${count(current.totalFiles)} 个文件`
									: tasks
										? "当前没有导入任务"
										: "暂无任务数据"
							}
							icon={<ArrowDownUpIcon className="h-4 w-4" />}
						/>
						<Metric
							label="待处理事项"
							value={data ? count(data.issues.length) : "—"}
							detail={data ? (data.issues.length ? "查看右侧异常汇总" : "已采集项目暂无异常") : "暂无数据"}
							icon={<ShieldCheckIcon className="h-4 w-4" />}
						/>
					</div>
					<div className="grid gap-5 xl:grid-cols-3">
						<Card className="shadow-none xl:col-span-2">
							<CardHeader className="flex flex-row items-center justify-between space-y-0">
								<CardTitle className="text-base">当前导入</CardTitle>
								<a
									href="https://resource.law100.xyz/"
									target="_blank"
									rel="noreferrer"
									className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
								>
									打开 Resource
									<ArrowUpRightIcon className="h-3.5 w-3.5" />
								</a>
							</CardHeader>
							<CardContent>
								{current ? (
									<div className="space-y-5">
										<div className="flex flex-wrap items-start justify-between gap-3">
											<div className="min-w-0">
												<h2 className="break-words font-medium">{current.label}</h2>
												<p className="mt-1 text-xs text-muted-foreground">
													{date(current.createdAt)} 开始 · 最近更新 {date(current.updatedAt)}
												</p>
											</div>
											<Badge warning={current.status === "needs_attention"}>
												{stateNames[current.status] ?? "状态未知"}
											</Badge>
										</div>
										<Meter value={current.percent} />
										<div className="flex flex-wrap justify-between gap-2 text-sm tabular-nums">
											<span>
												{count(current.completedFiles)} / {count(current.totalFiles)} 个文件已确认
											</span>
											<span className="text-muted-foreground">
												{bytes(current.completedBytes)} / {bytes(current.totalBytes)}
											</span>
										</div>
										<div className="grid grid-cols-3 gap-3 rounded-md bg-muted/40 p-4 text-sm">
											<div>
												<p className="text-xs text-muted-foreground">下载速度</p>
												<p className="mt-1 tabular-nums">
													{current.downloadBytesPerSecond != null ? `${bytes(current.downloadBytesPerSecond)}/s` : "—"}
												</p>
											</div>
											<div>
												<p className="text-xs text-muted-foreground">上传速度</p>
												<p className="mt-1 tabular-nums">
													{current.uploadBytesPerSecond != null ? `${bytes(current.uploadBytesPerSecond)}/s` : "—"}
												</p>
											</div>
											<div>
												<p className="text-xs text-muted-foreground">预计剩余</p>
												<p className="mt-1 tabular-nums">{duration(current.etaSeconds)}</p>
											</div>
										</div>
										{current.currentFile?.name && (
											<p className="truncate text-xs text-muted-foreground" title={current.currentFile.name}>
												当前文件：{current.currentFile.name}
											</p>
										)}
										{current.issue && (
											<p className="rounded-md border border-amber-500/25 bg-amber-500/5 p-3 text-sm text-amber-700 dark:text-amber-300">
												{current.issue}
											</p>
										)}
										<p className="text-xs text-muted-foreground">
											进度包含下载与上传；文件确认入库后才计为完成。速度不足以估算时不显示剩余时间。
										</p>
									</div>
								) : (
									<Empty>{tasks ? "当前没有正在导入的任务" : "暂无任务数据"}</Empty>
								)}
							</CardContent>
						</Card>
						<Card className="shadow-none">
							<CardHeader>
								<CardTitle className="text-base">异常汇总</CardTitle>
							</CardHeader>
							<CardContent>
								{data?.issues.length ? (
									<ul className="space-y-4">
										{data.issues.slice(0, 6).map((issue, i) => (
											<li key={`${issue.area}-${i}`} className="flex gap-3 text-sm">
												<AlertCircleIcon
													className={cn(
														"mt-0.5 h-4 w-4 shrink-0",
														issue.severity === "error" ? "text-destructive" : "text-amber-500"
													)}
												/>
												<span className="break-words leading-relaxed">{issue.title}</span>
											</li>
										))}
									</ul>
								) : (
									<div className="flex min-h-28 flex-col items-center justify-center gap-3 text-sm text-muted-foreground">
										<CheckCircle2Icon className="h-7 w-7 text-emerald-500" />
										{data ? "已采集项目暂无异常" : "暂无数据"}
									</div>
								)}
							</CardContent>
						</Card>
					</div>
					<div className="grid gap-5 xl:grid-cols-2">
						<Card className="shadow-none">
							<CardHeader>
								<CardTitle className="text-base">网盘账户</CardTitle>
							</CardHeader>
							<CardContent className="space-y-5">
								{accounts?.length ? (
									accounts.map((a) => (
										<div key={a.id} className="space-y-3 rounded-md border p-4">
											<div className="flex items-center justify-between gap-3">
												<div className="flex min-w-0 items-center gap-2">
													<HardDriveIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
													<span className="truncate text-sm font-medium">{a.name}</span>
												</div>
												<Badge warning={a.authorization !== "ready"}>
													{a.authorization === "ready"
														? "挂载正常"
														: a.authorization === "expired"
															? "授权已到期"
															: "需要检查"}
												</Badge>
											</div>
											<div className="flex justify-between gap-3 text-sm tabular-nums">
												<span>已用 {bytes(a.usedBytes)}</span>
												<span className="text-muted-foreground">共 {bytes(a.totalBytes)}</span>
											</div>
											<Meter value={a.usedBytes != null && a.totalBytes ? (a.usedBytes / a.totalBytes) * 100 : null} />
											<div className="flex flex-wrap justify-between gap-2 text-xs text-muted-foreground">
												<span>配置容量 · {a.usageState === "scanning" ? "统计更新中" : "缓存统计"}</span>
												<span>
													{a.scannedAt ? `${date(a.scannedAt)}${a.usageStale ? " · 待更新" : ""}` : "暂无已用量统计"}
												</span>
											</div>
											<p className="text-xs text-muted-foreground">记录授权到期：{date(a.expiresAt)}</p>
										</div>
									))
								) : (
									<Empty>{accounts ? "尚未接入网盘账户" : "暂无网盘数据"}</Empty>
								)}
							</CardContent>
						</Card>
						<Card className="shadow-none">
							<CardHeader className="flex flex-row items-center justify-between space-y-0">
								<CardTitle className="text-base">最近导入任务</CardTitle>
								<Badge>最近 6 项</Badge>
							</CardHeader>
							<CardContent>
								{history?.length ? (
									<div className="divide-y">
										{history.map((t) => (
											<div key={t.id} className="py-3 first:pt-0 last:pb-0">
												<div className="flex items-start justify-between gap-3">
													<span className="min-w-0 truncate text-sm font-medium" title={t.label}>
														{t.label}
													</span>
													<Badge>{stateNames[t.status]}</Badge>
												</div>
												<div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground tabular-nums">
													<span>
														{count(t.completedFiles)} 个文件 · {bytes(t.completedBytes)}
													</span>
													<span>历时 {duration(t.elapsedSeconds)}</span>
													<span title="按任务总历时计算，包含等待与暂停">
														全程平均 {t.averageBytesPerSecond != null ? `${bytes(t.averageBytesPerSecond)}/s` : "—"}
													</span>
												</div>
											</div>
										))}
									</div>
								) : (
									<Empty>{tasks ? "暂无已结束的任务" : "暂无任务数据"}</Empty>
								)}
							</CardContent>
						</Card>
					</div>
					<div className="grid gap-5 xl:grid-cols-2">
						<Card className="shadow-none">
							<CardHeader className="flex flex-row items-center justify-between space-y-0">
								<CardTitle className="text-base">资料库概况</CardTitle>
								<Badge>{data?.library ? `${count(data.library.shareCount)} 个分享` : "暂无数据"}</Badge>
							</CardHeader>
							<CardContent>
								<p className="mb-4 text-xs leading-relaxed text-muted-foreground">
									按已确认导入记录去重汇总；云盘后续的删除和改名未实时盘点。
								</p>
								{data?.library?.recent.length ? (
									<ul className="divide-y">
										{data.library.recent.map((r, i) => (
											<li
												key={`${r.label}-${i}`}
												className="flex items-center justify-between gap-3 py-3 text-sm first:pt-0 last:pb-0"
											>
												<span className="truncate" title={r.label}>
													{r.label}
												</span>
												<span className="shrink-0 text-xs text-muted-foreground tabular-nums">
													{count(r.fileCount)} 文件 · {bytes(r.totalBytes)}
												</span>
											</li>
										))}
									</ul>
								) : (
									<Empty>{data?.library ? "暂无已登记资料" : "暂无资料库数据"}</Empty>
								)}
							</CardContent>
						</Card>
						<Card className="shadow-none">
							<CardHeader>
								<CardTitle className="text-base">维护状态</CardTitle>
							</CardHeader>
							<CardContent className="space-y-5">
								<div className="flex items-start gap-3 rounded-md bg-muted/40 p-4">
									<DatabaseBackupIcon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
									<div className="min-w-0 flex-1">
										<div className="flex items-center justify-between gap-3 text-sm">
											<span className="font-medium">自动备份</span>
											<Badge warning={!data?.maintenance?.backup || data.maintenance.backup.state !== "ready"}>
												{!data?.maintenance?.backup
													? "暂无数据"
													: data.maintenance.backup.state === "ready" && data.maintenance.backup.verified
														? "已完成校验"
														: "需要检查"}
											</Badge>
										</div>
										<p className="mt-2 text-xs text-muted-foreground">
											{data?.maintenance?.backup
												? `${date(data.maintenance.backup.completedAt)} · ${bytes(data.maintenance.backup.sizeBytes)}`
												: "暂无备份数据"}
										</p>
										<p className="mt-1 text-xs text-muted-foreground">本机备份，尚未配置异地备份。</p>
									</div>
								</div>
								<div className="space-y-3">
									{data?.maintenance?.certificates.map((c) => (
										<div key={c.domain} className="flex items-center justify-between gap-3 text-xs">
											<span className="truncate text-muted-foreground">{c.domain}</span>
											<span
												className={cn(
													"shrink-0 tabular-nums",
													c.daysRemaining != null && c.daysRemaining < 14 && "text-amber-600 dark:text-amber-300"
												)}
											>
												{c.daysRemaining == null
													? "暂无证书数据"
													: c.daysRemaining < 0
														? "已过期"
														: `证书剩余 ${c.daysRemaining} 天`}
											</span>
										</div>
									))}
								</div>
							</CardContent>
						</Card>
					</div>
					<footer className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
						<ClockIcon className="h-3.5 w-3.5" />
						页面可见时每 15 秒更新，仅展示数据，不执行网盘或任务操作。
					</footer>
				</>
			)}
		</div>
	)
}
