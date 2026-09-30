import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { Capture } from '@m3u8-bridge/protocol';
import { EngineClient } from '@m3u8-bridge/protocol';
import { AppShell, ResourceList, SectionTitle } from '@m3u8-bridge/ui';
import { submitWithDesktopLaunch } from './desktop-launch';
import '@m3u8-bridge/ui/src/styles.css';

function Popup() {
  const client = useMemo(() => new EngineClient(), []);
  const [captures, setCaptures] = useState<Capture[]>([]);
  const [message, setMessage] = useState('');
  const refresh = () => chrome.storage.session.get('captures').then(value => setCaptures((value.captures as Capture[] | undefined) ?? []));
  useEffect(() => {
    void refresh();
    const listener = () => { void refresh(); };
    chrome.storage.onChanged.addListener(listener);
    return () => chrome.storage.onChanged.removeListener(listener);
  }, []);
  const download = async (capture: Capture) => {
    try {
      await submitWithDesktopLaunch(() => client.createJob({ capture }), url => chrome.tabs.create({ url }));
      setMessage('已提交到桌面端');
      void client.activateApp().catch(() => undefined);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '提交失败，请打开桌面端后重试');
    }
  };
  return <AppShell compact><SectionTitle title="发现的媒体" detail={message || `${captures.length} 个资源`} /><ResourceList captures={captures} onDownload={capture => { void download(capture); }} /></AppShell>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><Popup /></React.StrictMode>);
