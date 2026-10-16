/** Revoke the server session before clearing the local Beszel state. */
export async function endUnifiedSession(request: typeof fetch = fetch, basePath = "") {
	const options: RequestInit = { credentials: "same-origin", cache: "no-store", redirect: "error" }
	const session = await request(`${basePath}/_auth/session`, options)
	if (!session.ok) throw new Error("无法核对登录状态，请稍后重试。")
	const identity = (await session.json())?.data
	if (identity?.authenticated === false) return
	if (identity?.authenticated !== true || typeof identity.csrfToken !== "string" || !identity.csrfToken) {
		throw new Error("无法核对登录状态，请刷新后重试。")
	}
	const response = await request(`${basePath}/_auth/logout`, {
		...options,
		method: "POST",
		headers: { "Content-Type": "application/json", "X-Auth-CSRF": identity.csrfToken },
		body: "{}",
	})
	if (!response.ok || (await response.json())?.data?.authenticated !== false) {
		throw new Error("退出尚未完成，请重试。")
	}
}
