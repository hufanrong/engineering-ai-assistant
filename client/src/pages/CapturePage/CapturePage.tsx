import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';
import { toast } from 'sonner';
import {
  BookOpen,
  Camera,
  ClipboardCheck,
  FileDiff,
  FileText,
  FlaskConical,
  Layers,
  ListChecks,
  Loader2,
  MessageSquare,
  Mic,
  Package,
  PenLine,
  Ruler,
  TriangleAlert,
  Truck,
} from 'lucide-react';

import { Button } from '@client/src/components/ui/button';
import { Label } from '@client/src/components/ui/label';
import { Skeleton } from '@client/src/components/ui/skeleton';
import { Textarea } from '@client/src/components/ui/textarea';
import { getDataloom } from '@lark-apaas/client-toolkit/dataloom';
import { getDefaultBucketId } from '@lark-apaas/client-toolkit/tools/storage';
import {
  captureWithFile,
  createRecord,
  getCaptureResult,
  getRecordTypeConfigs,
  listSiteRecords,
} from '@client/src/api/record';
import type { RecordListItem, RecordTypeConfigItem } from '@shared/api.interface';
import { RECORD_STATUS } from '@shared/api.interface';
import { formatRelativeTime } from '@client/src/utils/time';
import { voiceBlobToWav } from './voice-wav';
import ProjectSelector from './ProjectSelector';
import CaptureResultPanel, { type CaptureResultData } from './CaptureResultPanel';

const AUDIO_MIME_CANDIDATES = ['audio/ogg;codecs=opus', 'audio/webm;codecs=opus', 'audio/mp4'];
const POLL_INTERVAL_MS = 2000;
const MAX_POLL_COUNT = 75;

const TYPE_ICON_MAP: Record<string, typeof FileText> = {
  opening_record: ClipboardCheck,
  concealed_record: Layers,
  inspection_batch: ListChecks,
  equipment_arrival: Package,
  construction_log: PenLine,
  material_arrival: Truck,
  test_report: FlaskConical,
  measurement_record: Ruler,
  disclosure: MessageSquare,
  design_change: FileDiff,
  damage_record: TriangleAlert,
  ledger: BookOpen,
};

function pickMimeType(): string {
  if (typeof MediaRecorder === 'undefined') {
    return '';
  }
  return AUDIO_MIME_CANDIDATES.find((t) => MediaRecorder.isTypeSupported(t)) ?? '';
}

function extOf(mimeType: string): string {
  if (mimeType.includes('ogg')) return 'ogg';
  if (mimeType.includes('webm')) return 'webm';
  if (mimeType.includes('mp4')) return 'mp4';
  return 'wav';
}

interface PendingVoice {
  file: File;
  url: string;
  seconds: number;
}

const CapturePage = () => {
  const navigate = useNavigate();
  const [projectId, setProjectId] = useState<string | null>(
    () => localStorage.getItem('capture_project_id') || null,
  );
  const [workshopId, setWorkshopId] = useState<string | null>(
    () => localStorage.getItem('capture_workshop_id') || null,
  );
  const [typeConfigs, setTypeConfigs] = useState<RecordTypeConfigItem[]>([]);
  const [recent, setRecent] = useState<RecordListItem[]>([]);
  const [recentLoading, setRecentLoading] = useState(true);

  const [text, setText] = useState('');
  const [submittingText, setSubmittingText] = useState(false);
  const [phase, setPhase] = useState<'idle' | 'recognizing' | 'result'>('idle');
  const [resultData, setResultData] = useState<CaptureResultData | null>(null);

  const [recording, setRecording] = useState(false);
  const [recordSeconds, setRecordSeconds] = useState(0);
  const [pendingVoice, setPendingVoice] = useState<PendingVoice | null>(null);

  const photoInputRef = useRef<HTMLInputElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const recordSecondsRef = useRef(0);
  const pendingVoiceUrlRef = useRef<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const data = await getRecordTypeConfigs();
        setTypeConfigs(data.items);
      } catch {
        toast.error('加载记录类型配置失败');
      }
    })();
  }, []);

  const refreshRecent = useCallback(async () => {
    try {
      const data = await listSiteRecords({ creator: 'me', limit: 10 });
      setRecent(data.items);
    } catch {
      setRecent([]);
    } finally {
      setRecentLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshRecent();
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
      if (timerRef.current) clearInterval(timerRef.current);
      streamRef.current?.getTracks().forEach((track) => track.stop());
      if (pendingVoiceUrlRef.current) URL.revokeObjectURL(pendingVoiceUrlRef.current);
    };
  }, [refreshRecent]);

  const handleProjectChange = (nextProjectId: string, nextWorkshopId: string | null) => {
    setProjectId(nextProjectId);
    setWorkshopId(nextWorkshopId);
    localStorage.setItem('capture_project_id', nextProjectId);
    if (nextWorkshopId) {
      localStorage.setItem('capture_workshop_id', nextWorkshopId);
    } else {
      localStorage.removeItem('capture_workshop_id');
    }
  };

  const refreshAfterCapture = () => {
    setPhase('idle');
    setResultData(null);
    setPendingVoice(null);
    void refreshRecent();
  };

  const clearPendingVoice = (next: PendingVoice | null) => {
    if (pendingVoiceUrlRef.current) URL.revokeObjectURL(pendingVoiceUrlRef.current);
    pendingVoiceUrlRef.current = next?.url ?? null;
    setPendingVoice(next);
  };

  const pollCaptureResult = (taskId: string, recordId: string, attempt: number) => {
    if (attempt > MAX_POLL_COUNT) {
      toast.error('识别超时，请稍后在记录管理中查看结果');
      refreshAfterCapture();
      return;
    }
    pollTimerRef.current = setTimeout(() => {
      void (async () => {
        try {
          const result = await getCaptureResult(taskId);
          if (result.status === 'running') {
            pollCaptureResult(taskId, recordId, attempt + 1);
            return;
          }
          if (result.status === 'failed') {
            toast.error(`识别失败：${result.message ?? '未知原因'}`);
            refreshAfterCapture();
            return;
          }
          setResultData({
            recordId,
            recordType: result.recordType ?? 'other',
            recordTypeName: result.recordTypeName ?? '其他',
            typeConfidence: result.typeConfidence ?? 0,
            content: result.content ?? '',
            missingFields: result.missingFields ?? [],
            completeness: result.completeness ?? 0,
            status: 'pending',
          });
          setPhase('result');
          void refreshRecent();
        } catch {
          toast.error('查询识别结果失败');
          refreshAfterCapture();
        }
      })();
    }, POLL_INTERVAL_MS);
  };

  const startCaptureFlow = async (file: File, source: 'mobile_photo' | 'mobile_voice') => {
    if (!projectId) {
      toast.error('请先选择项目');
      return;
    }
    setPhase('recognizing');
    try {
      const dataloom = await getDataloom();
      const { data, error } = await dataloom.storage
        .from(getDefaultBucketId())
        .uploadFile(file);
      if (error || !data) {
        const message =
          error && 'error_msg' in error && typeof error.error_msg === 'string'
            ? error.error_msg
            : error?.message ?? '上传失败';
        throw new Error(message);
      }
      const created = await captureWithFile({
        fileUrl: data.download_url,
        projectId,
        workshopId: workshopId ?? undefined,
        recordDate: dayjs().format('YYYY-MM-DD'),
        source,
      });
      pollCaptureResult(created.taskId, created.recordId, 1);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '上传失败，请重试');
      setPhase('idle');
    }
  };

  const confirmVoiceUpload = () => {
    if (!pendingVoice) return;
    const file = pendingVoice.file;
    clearPendingVoice(null);
    void startCaptureFlow(file, 'mobile_voice');
  };

  const cancelVoiceUpload = () => {
    clearPendingVoice(null);
  };

  const handlePhotoChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (photoInputRef.current) {
      photoInputRef.current.value = '';
    }
    if (file) {
      void startCaptureFlow(file, 'mobile_photo');
    }
  };

  const startVoiceRecording = async () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      return;
    }
    if (!projectId) {
      toast.error('请先选择项目');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = pickMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };
      recorder.onstop = () => {
        const mimeType = recorder.mimeType || 'audio/webm';
        const rawBlob = new Blob(chunksRef.current, { type: mimeType });
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        if (rawBlob.size === 0) {
          setPhase('idle');
          return;
        }
        void (async () => {
          const converted = await voiceBlobToWav(rawBlob);
          const finalBlob = converted?.blob ?? rawBlob;
          const filename = converted
            ? `voice-${Date.now()}.wav`
            : `voice-${Date.now()}.${extOf(mimeType)}`;
          const file = new File([finalBlob], filename, { type: finalBlob.type });
          clearPendingVoice({
            file,
            url: URL.createObjectURL(finalBlob),
            seconds: converted?.durationSec ?? recordSecondsRef.current,
          });
        })();
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setRecording(true);
      setRecordSeconds(0);
      recordSecondsRef.current = 0;
      timerRef.current = setInterval(() => {
        recordSecondsRef.current += 1;
        setRecordSeconds((prev) => prev + 1);
      }, 1000);
    } catch {
      toast.error('无法访问麦克风，请检查浏览器权限');
    }
  };

  const stopVoiceRecording = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    setRecording(false);
  };

  const handleSubmitText = async () => {
    if (!projectId) {
      toast.error('请先选择项目');
      return;
    }
    if (text.trim().length === 0) {
      toast.error('请输入记录内容');
      return;
    }
    setSubmittingText(true);
    try {
      const created = await createRecord({
        projectId,
        workshopId: workshopId ?? undefined,
        content: text.trim(),
        recordDate: dayjs().format('YYYY-MM-DD'),
        source: 'mobile_text',
      });
      setResultData({
        recordId: created.id,
        recordType: created.recordType,
        recordTypeName: created.recordTypeName,
        typeConfidence: created.typeConfidence,
        content: text.trim(),
        missingFields: created.missingFields,
        completeness: created.completeness,
        status: created.status,
      });
      setPhase('result');
      setText('');
      void refreshRecent();
    } catch {
      toast.error('提交失败，请重试');
    } finally {
      setSubmittingText(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-[calc(100vh-4rem)] w-full max-w-md flex-col gap-4 p-4">
      <ProjectSelector
        projectId={projectId}
        workshopId={workshopId}
        onChange={handleProjectChange}
      />

      {phase === 'recognizing' && (
        <div className="flex flex-col items-center justify-center gap-3 rounded-md border border-border bg-card p-10 shadow-xs">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <div className="text-sm text-muted-foreground">识别中，请稍候...</div>
        </div>
      )}

      {phase === 'result' && resultData && (
        <CaptureResultPanel
          key={resultData.recordId}
          data={resultData}
          typeConfigs={typeConfigs}
          onDone={refreshAfterCapture}
        />
      )}

      {phase === 'idle' && pendingVoice && (
        <div className="rounded-md border border-primary/30 bg-card p-4 shadow-xs">
          <div className="flex items-center gap-3">
            <Mic className="h-8 w-8 shrink-0 text-primary" />
            <div className="min-w-0">
              <p className="text-sm font-semibold">语音已录制，待确认</p>
              <p className="font-mono tabular-nums text-xs text-muted-foreground">
                {String(Math.floor(pendingVoice.seconds / 60)).padStart(2, '0')}:
                {String(pendingVoice.seconds % 60).padStart(2, '0')}
              </p>
            </div>
          </div>
          <audio
            src={pendingVoice.url}
            controls
            preload="metadata"
            className="mt-3 w-full"
          />
          <p className="mt-2 text-xs text-muted-foreground">
            请试听确认后上传，取消则不会提交录音
          </p>
          <div className="mt-3 flex gap-2">
            <Button
              variant="outline"
              className="flex-1"
              onClick={cancelVoiceUpload}
            >
              取消
            </Button>
            <Button className="flex-1" onClick={confirmVoiceUpload}>
              确认上传
            </Button>
          </div>
        </div>
      )}

      {phase === 'idle' && (
        <div data-ai-section-type="card-list" className="flex flex-1 flex-col gap-4">
          <label
            data-ai-section-type="button"
            className="flex flex-col items-center justify-center gap-2 rounded-md border border-border bg-card py-10 shadow-xs transition-colors active:border-primary"
          >
            <Camera className="h-10 w-10 text-primary" />
            <span className="text-lg font-semibold">拍照采集</span>
            <span className="text-xs text-muted-foreground">拍摄现场照片，自动识别结构化信息</span>
            <input
              ref={photoInputRef}
              type="file"
              accept="image/*"
              capture
              className="hidden"
              onChange={handlePhotoChange}
            />
          </label>

          <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-border bg-card py-8 shadow-xs">
            <button
              type="button"
              data-ai-section-type="button"
              aria-label={recording ? '停止录音' : '开始录音'}
              onClick={() => (recording ? stopVoiceRecording() : void startVoiceRecording())}
              className={`flex h-20 w-20 select-none items-center justify-center rounded-full border-4 transition-colors ${
                recording
                  ? 'border-destructive bg-destructive/15'
                  : 'border-primary/40 bg-primary/10 active:border-primary'
              }`}
            >
              <Mic
                className={`h-8 w-8 ${recording ? 'animate-pulse text-destructive' : 'text-primary'}`}
              />
            </button>
            <span className="text-lg font-semibold">
              {recording ? '点击停止录音' : '点击开始录音'}
            </span>
            <span className="font-mono tabular-nums text-xs text-muted-foreground">
              {recording
                ? `录音中 ${String(Math.floor(recordSeconds / 60)).padStart(2, '0')}:${String(recordSeconds % 60).padStart(2, '0')}`
                : '点击上方按钮开始录音，停止后试听并确认上传'}
            </span>
          </div>

          <div className="rounded-md border border-border bg-card p-4 shadow-xs">
            <Label htmlFor="capture-text" className="text-base">
              文字采集
            </Label>
            <Textarea
              id="capture-text"
              placeholder="输入现场记录内容，自动识别类型与缺失项"
              value={text}
              rows={5}
              onChange={(e) => setText(e.target.value)}
              className="mt-2"
            />
            <Button className="mt-3 w-full" disabled={submittingText} onClick={() => void handleSubmitText()}>
              {submittingText ? '提交中...' : '提交记录'}
            </Button>
          </div>
        </div>
      )}

      <div>
        <div className="mb-2 text-sm font-medium">最近上传</div>
        {recentLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
          </div>
        ) : recent.length === 0 ? (
          <div className="rounded-md border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
            暂无采集记录
          </div>
        ) : (
          <div className="space-y-2">
            {recent.map((item) => {
              const Icon = TYPE_ICON_MAP[item.recordType] ?? FileText;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => navigate(`/records?projectId=${item.projectId}`)}
                  className="flex w-full items-center gap-3 rounded-md border border-border bg-card p-3 text-left shadow-xs transition-colors hover:border-primary/40"
                >
                  <Icon className="h-5 w-5 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm">{item.title}</div>
                    <div className="text-xs text-muted-foreground">
                      {item.recordTypeName} · {formatRelativeTime(item.createdAt)}
                    </div>
                  </div>
                  {item.status === RECORD_STATUS.PENDING_SUPPLEMENT && (
                    <span className="badge-warning shrink-0 rounded-full px-2 py-0.5 text-xs font-medium">
                      待补充
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

export default CapturePage;
