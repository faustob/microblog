import { onLCP, onINP } from 'https://unpkg.com/web-vitals@4?module';

function sendToServer(metric) {
    const routeMeta = document.querySelector('meta[name="route-template"]');
    const route = routeMeta ? routeMeta.content : window.location.pathname;
    const body = JSON.stringify({
        name: metric.name,
        value: metric.value,
        route: route,
    });
    try {
        if (navigator.sendBeacon) {
            const blob = new Blob([body], { type: 'application/json' });
            navigator.sendBeacon('/api/vitals', blob);
        } else {
            fetch('/api/vitals', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: body,
                keepalive: true,
            });
        }
    } catch (e) {
        // swallow reporting errors, never break the page
    }
}

onLCP(sendToServer);
onINP(sendToServer);
