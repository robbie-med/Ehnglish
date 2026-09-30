import { useTranslation } from 'react-i18next';
import type { Lang } from './i18n';

export function useLang(): Lang {
  const { i18n } = useTranslation();
  return i18n.language.startsWith('ko') ? 'ko' : 'en';
}
