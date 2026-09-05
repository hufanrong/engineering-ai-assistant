import dayjs from 'dayjs';

export function formatRelativeTime(value: string): string {
  const time = dayjs(value);
  const diffMinutes = dayjs().diff(time, 'minute');
  if (diffMinutes < 1) {
    return '刚刚';
  }
  if (diffMinutes < 60) {
    return `${diffMinutes} 分钟前`;
  }
  const diffHours = dayjs().diff(time, 'hour');
  if (diffHours < 24) {
    return `${diffHours} 小时前`;
  }
  const diffDays = dayjs().diff(time, 'day');
  if (diffDays < 30) {
    return `${diffDays} 天前`;
  }
  return time.format('YYYY-MM-DD');
}

export function formatDateTime(value: string): string {
  return dayjs(value).format('YYYY-MM-DD HH:mm');
}

export function formatDate(value: string): string {
  return dayjs(value).format('YYYY-MM-DD');
}
