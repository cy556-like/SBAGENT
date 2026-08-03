/**
 * DocAgent Service Worker
 * PWA 离线缓存与资源管理
 * 版本: 1.3.0
 */

const CACHE_VERSION = 'v1.3.1-20260803';
const CACHE_NAME = `sbagent-${CACHE_VERSION}`;
const STATIC_CACHE = `sbagent-static-${CACHE_VERSION}`;
const DYNAMIC_CACHE = `sbagent-dynamic-${CACHE_VERSION}`;

// 需要预缓存的静态资源
const PRECACHE_URLS = [
    '/',
    '/static/css/style.css?v=20260803-cache2',
    '/static/js/subagents-data.js?v=20260803-cache2',
    '/static/js/app.js?v=20260803-cache2',
    '/static/manifest.json?v=20260803-cache2',
    '/static/icons/icon-gy.svg?v=20260803-cache2',
    '/static/icons/icon-192.png?v=20260803-cache2',
    '/static/icons/icon-512.png?v=20260803-cache2',
];

// 不缓存的路径（API请求、流式响应等）
const NO_CACHE_PATTERNS = [
    /\/api\/v1\//,         // API请求
    /\/stream/,             // 流式响应
    /\/upload/,             // 文件上传
];

// 安装事件 - 预缓存关键资源
self.addEventListener('install', (event) => {
    console.log('[SW] Install');
    event.waitUntil(
        caches.open(STATIC_CACHE).then((cache) => {
            console.log('[SW] Pre-caching static resources');
            return cache.addAll(PRECACHE_URLS);
        }).catch((err) => {
            console.warn('[SW] Pre-cache failed (offline?):', err);
        })
    );
    // 立即激活，不等待旧SW关闭
    self.skipWaiting();
});

// 激活事件 - 清理旧缓存
self.addEventListener('activate', (event) => {
    console.log('[SW] Activate');
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames
                    .filter((name) =>
                        name.startsWith('sbagent-') &&
                        name !== STATIC_CACHE &&
                        name !== DYNAMIC_CACHE
                    )
                    .map((name) => {
                        console.log('[SW] Removing old cache:', name);
                        return caches.delete(name);
                    })
            );
        })
    );
    self.clients.claim();
});

// 请求拦截策略
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // 跳过非同源请求
    if (url.origin !== location.origin) return;
    if (request.method !== 'GET') return;

    // 跳过不需要缓存的请求
    if (NO_CACHE_PATTERNS.some(pattern => pattern.test(url.pathname))) {
        return;
    }

    // 对于导航请求（HTML页面），使用网络优先策略
    if (request.mode === 'navigate') {
        event.respondWith(networkFirst(request));
        return;
    }

    // 所有本地静态资源均使用网络优先：
    // 普通刷新会重新校验 JS、CSS、图片、头像、Logo 和字体，
    // 网络不可用时才读取上一次成功缓存的版本。
    if (isStaticAsset(url.pathname)) {
        event.respondWith(networkFirst(request));
        return;
    }

    // 其他请求，使用网络优先策略
    event.respondWith(networkFirst(request));
});

// 网络优先策略（适合频繁更新的内容）
async function networkFirst(request) {
    try {
        // no-cache 表示允许浏览器使用 304，但必须先向服务器确认资源是否变化。
        const response = await fetch(request, { cache: 'no-cache' });
        if (response.ok) {
            const cache = await caches.open(
                isStaticAsset(new URL(request.url).pathname) ? STATIC_CACHE : DYNAMIC_CACHE
            );
            cache.put(request, response.clone());
        }
        return response;
    } catch (err) {
        const cached = await caches.match(request);
        if (cached) return cached;

        // 如果是导航请求，返回离线页面
        if (request.mode === 'navigate') {
            return caches.match('/');
        }

        return new Response('离线状态', {
            status: 503,
            headers: { 'Content-Type': 'text/plain; charset=utf-8' }
        });
    }
}

// 判断是否为静态资源
function isStaticAsset(pathname) {
    return (
        pathname === '/static/manifest.json' ||
        /\.(css|js|png|jpg|jpeg|gif|webp|avif|svg|ico|woff|woff2|ttf|eot)$/i.test(pathname)
    );
}

// 监听消息 - 允许前端触发缓存更新
self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
    if (event.data && event.data.type === 'CLEAR_CACHE') {
        caches.keys().then((names) => {
            names.forEach((name) => caches.delete(name));
        });
    }
});
