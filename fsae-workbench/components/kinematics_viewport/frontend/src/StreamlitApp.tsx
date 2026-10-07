import { useCallback, useEffect, useMemo, useState } from "react";
import { Streamlit, type RenderData } from "streamlit-component-lib/dist/streamlit";
import { KinematicsViewport } from "./KinematicsViewport";
import { normalizePayload, type ViewportEvent, type ViewportPayload } from "./types";

interface Args {
  payload?: Partial<ViewportPayload>;
  height?: number;
}

const DEFAULT_HEIGHT = 620;

export function StreamlitApp() {
  const [renderData, setRenderData] = useState<RenderData<Args> | null>(null);

  useEffect(() => {
    const onRender = (event: Event) => {
      setRenderData((event as CustomEvent<RenderData<Args>>).detail);
    };
    Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, onRender);
    Streamlit.setComponentReady();
    return () => {
      Streamlit.events.removeEventListener(Streamlit.RENDER_EVENT, onRender);
    };
  }, []);

  const height = renderData?.args?.height ?? DEFAULT_HEIGHT;

  useEffect(() => {
    Streamlit.setFrameHeight(height);
  }, [height, renderData]);

  const payload = useMemo(
    () => normalizePayload(renderData?.args?.payload),
    [renderData],
  );

  const handleEvent = useCallback((event: ViewportEvent) => {
    Streamlit.setComponentValue(event);
  }, []);

  if (!renderData) {
    return <div style={{ height, color: "#94a3b8", font: "12px system-ui" }}>Loading viewport…</div>;
  }

  return <KinematicsViewport payload={payload} height={height} onEvent={handleEvent} />;
}
