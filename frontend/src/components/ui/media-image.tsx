/**
 * Plain <img> wrapper for auth-proxied media.
 *
 * next/image is deliberately NOT used here: all media is served through the
 * auth-gated same-origin proxy (/api/media/... via fileUrl()/apiUrl()), which
 * requires the viewer's session cookie. next/image's optimizer fetches the
 * source server-side WITHOUT that cookie and gets a 401. Server-side resizing
 * already happens in the backend proxy via the ?w= query param, so the
 * optimizer would add nothing even if it could authenticate.
 */
import React from "react";

export function MediaImage({
  alt = "",
  loading = "lazy",
  decoding = "async",
  ...rest
}: React.ImgHTMLAttributes<HTMLImageElement>) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img alt={alt} loading={loading} decoding={decoding} {...rest} />
  );
}
