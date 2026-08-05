import { type ChangeEvent, useState } from "react";
import { uploadProfileAvatar } from "../api";

interface Props {
  avatarUrl: string | null;
  onUploaded: (avatarUrl: string) => void;
}

const ALLOWED_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const MAX_BYTES = 5 * 1024 * 1024;

export function ProfileAvatar({ avatarUrl, onUploaded }: Props) {
  const [message, setMessage] = useState("");

  async function selectAvatar(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0];
    if (!file) return;
    if (!ALLOWED_TYPES.has(file.type) || file.size > MAX_BYTES) {
      setMessage("请选择不超过 5 MB 的 PNG、JPEG 或 WebP 图片");
      input.value = "";
      return;
    }
    setMessage("正在保存…");
    try {
      const result = await uploadProfileAvatar(file);
      onUploaded(result.avatar_url);
      setMessage("头像已保存");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "头像保存失败");
    } finally {
      input.value = "";
    }
  }

  return <div className="avatar-control">
    <label className="avatar-picker" title="点击上传个人头像">
      <span className="avatar">
        {avatarUrl
          ? <img src={avatarUrl} alt="个人头像" />
          : <span aria-hidden="true">👤</span>}
      </span>
      <input
        className="sr-only"
        type="file"
        accept="image/png,image/jpeg,image/webp"
        aria-label="上传个人头像"
        onChange={(event) => void selectAvatar(event)}
      />
    </label>
    {message && <span className="avatar-upload-status" role="status">{message}</span>}
  </div>;
}
