import { Box, Button } from "@chakra-ui/react";
import { FiTrash2 } from "react-icons/fi";
import { formatDistanceToNow } from "date-fns";
import { zhCN, enUS } from "date-fns/locale";
import { memo } from "react";
import { useTranslation } from "react-i18next";
import {
  DrawerRoot,
  DrawerTrigger,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerBody,
  DrawerFooter,
  DrawerActionTrigger,
  DrawerBackdrop,
  DrawerCloseTrigger,
} from "@/components/ui/drawer";
import { sidebarStyles } from "./sidebar-styles";
import { useHistoryDrawer } from "@/hooks/sidebar/use-history-drawer";
import { HistoryInfo } from "@/context/websocket-context";
import { useCompanion } from "@/components/companion/companion-context";

// Type definitions
interface HistoryDrawerProps {
  children: React.ReactNode;
}

interface HistoryItemProps {
  isSelected: boolean;
  latestMessage: { content: string; timestamp: string | null };
  onSelect: () => void;
  onDelete: (e: React.MouseEvent) => void;
  isDeleteDisabled: boolean;
}

// Reusable components
const HistoryItem = memo(
  ({
    isSelected,
    latestMessage,
    onSelect,
    onDelete,
    isDeleteDisabled,
  }: HistoryItemProps): JSX.Element => {
    const { t, i18n } = useTranslation();
    return (
      <Box
        {...sidebarStyles.historyDrawer.historyItem}
        {...(isSelected ? sidebarStyles.historyDrawer.historyItemSelected : {})}
      >
        <Box display="flex" gap={3} alignItems="start">
          <button
            type="button"
            onClick={onSelect}
            style={{ flex: 1, minWidth: 0, textAlign: "left" }}
            aria-current={isSelected ? "true" : undefined}
          >
            <Box {...sidebarStyles.historyDrawer.messagePreview} mb={2}>
              {latestMessage.content || "还没有消息"}
            </Box>
            <Box {...sidebarStyles.historyDrawer.timestamp}>
              {latestMessage.timestamp
                ? formatDistanceToNow(new Date(latestMessage.timestamp), {
                    addSuffix: true,
                    locale: i18n.language.startsWith("zh") ? zhCN : enUS,
                  })
                : t("history.noMessages")}
            </Box>
          </button>
          <Button
            aria-label="删除这段聊天"
            onClick={onDelete}
            disabled={isDeleteDisabled}
            {...sidebarStyles.historyDrawer.deleteButton}
          >
            <FiTrash2 />
          </Button>
        </Box>
      </Box>
    );
  },
);

HistoryItem.displayName = "HistoryItem";

// Main component
function HistoryDrawer({ children }: HistoryDrawerProps): JSX.Element {
  const { t } = useTranslation();
  const { profile } = useCompanion();
  const {
    open,
    setOpen,
    historyList,
    currentHistoryUid,
    fetchAndSetHistory,
    deleteHistory,
    getLatestMessageContent,
  } = useHistoryDrawer();

  return (
    <DrawerRoot
      open={open}
      onOpenChange={(e) => setOpen(e.open)}
      placement="start"
    >
      <DrawerBackdrop />
      <DrawerTrigger asChild>{children}</DrawerTrigger>
      <DrawerContent style={sidebarStyles.historyDrawer.drawer.content}>
        <DrawerHeader>
          <DrawerTitle style={sidebarStyles.historyDrawer.drawer.title}>
            {t("history.chatHistoryList")}
          </DrawerTitle>
          <DrawerCloseTrigger
            style={sidebarStyles.historyDrawer.drawer.closeButton}
          />
        </DrawerHeader>

        <DrawerBody>
          <Box color="whiteAlpha.700" fontSize="sm" mb={4}>
            {profile?.synthetic_demo
              ? "示例体验：这里不显示你的个人聊天记录。"
              : profile?.trial_mode
                ? `当前为体验档案 ${profile.label}`
                : `个人档案 · ${historyList.length} 段已保存的对话`}
            {profile?.trial_mode && !profile.consent?.retain_conversation && (
              <Box mt={2}>
                当前未开启聊天内容保存，本次交流仅在当前页面保留。
              </Box>
            )}
          </Box>
          {historyList.length === 0 && (
            <Box color="whiteAlpha.600" py={8}>
              还没有保存的聊天记录。
            </Box>
          )}
          <Box {...sidebarStyles.historyDrawer.listContainer}>
            {historyList.map((history: HistoryInfo) => (
              <HistoryItem
                key={history.uid}
                isSelected={currentHistoryUid === history.uid}
                latestMessage={getLatestMessageContent(history)}
                onSelect={() => fetchAndSetHistory(history.uid)}
                onDelete={(e) => {
                  e.stopPropagation();
                  deleteHistory(history.uid);
                }}
                isDeleteDisabled={currentHistoryUid === history.uid}
              />
            ))}
          </Box>
        </DrawerBody>

        <DrawerFooter>
          <DrawerActionTrigger asChild>
            <Button {...sidebarStyles.historyDrawer.drawer.actionButton}>
              {t("common.close")}
            </Button>
          </DrawerActionTrigger>
        </DrawerFooter>
      </DrawerContent>
    </DrawerRoot>
  );
}

export default HistoryDrawer;
