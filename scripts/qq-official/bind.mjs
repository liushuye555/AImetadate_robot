// Credentials travel only over the private stdout pipe to Python, never the UI.
import { startQrConnect } from '@tencent-connect/qqbot-connector';
import QRCode from 'qrcode';
import { resolve } from 'node:path';

const png = resolve(process.argv[2]);
const send = value => process.stdout.write(JSON.stringify(value) + '\n');
console.log = () => {};
console.error = () => {};
const controller = new AbortController();
let done = false;
const timer = setTimeout(() => {
  if (done) return;
  done = true;
  controller.abort();
  send({ phase: 'failed', error: '扫码等待超时，请重新连接' });
}, 300_000);
startQrConnect({
  onQrDisplayed: async url => {
    try {
      await QRCode.toFile(png, url, { width: 360, margin: 3 });
      if (!done) send({ phase: 'waiting', url, image: png });
    } catch { send({ phase: 'failed', error: '无法生成绑定二维码' }); }
  },
  onQrExpired: () => { if (!done) send({ phase: 'expired' }); },
  onSuccess: credentials => {
    if (done) return;
    done = true;
    clearTimeout(timer);
    send({ phase: 'credentials', credentials });
    controller.abort();
  },
  onFailure: () => {
    if (done) return;
    done = true;
    clearTimeout(timer);
    send({ phase: 'failed', error: 'QQ 官方扫码连接失败，请稍后重试' });
  },
}, { displayQrCodeToConsole: false, signal: controller.signal, source: 'qq-onebot-whitelist' });
