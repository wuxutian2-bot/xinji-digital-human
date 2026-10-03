/* eslint-disable react/require-default-props */
import { Box, Button } from "@chakra-ui/react";
import { FiSettings, FiClock, FiPlus, FiChevronLeft } from "react-icons/fi";
import { sidebarStyles } from "./sidebar-styles";
import SettingUI from "./setting/setting-ui";
import ChatHistoryPanel from "./chat-history-panel";
import HistoryDrawer from "./history-drawer";
import { useSidebar } from "@/hooks/sidebar/use-sidebar";
import { CompanionEntry } from "@/components/companion/companion-controls";

interface SidebarProps {
  isCollapsed?: boolean;
  onToggle: () => void;
}

function Sidebar({ isCollapsed = false, onToggle }: SidebarProps): JSX.Element {
  const { settingsOpen, onSettingsOpen, onSettingsClose, createNewHistory } =
    useSidebar();
  return (
    <Box {...sidebarStyles.sidebar.container(isCollapsed)}>
      <Button
        aria-label={isCollapsed ? "展开聊天与心迹" : "收起聊天与心迹"}
        {...sidebarStyles.sidebar.toggleButton}
        style={{ transform: isCollapsed ? "rotate(180deg)" : "rotate(0deg)" }}
        onClick={onToggle}
      >
        <FiChevronLeft />
      </Button>
      {!isCollapsed && !settingsOpen && (
        <Box {...sidebarStyles.sidebar.content}>
          <div className="xj xj-chat-tools">
            <HistoryDrawer>
              <button aria-label="聊天记录">
                <FiClock />
                <span>聊天记录</span>
              </button>
            </HistoryDrawer>
            <button aria-label="新建聊天" onClick={createNewHistory}>
              <FiPlus />
              <span>新聊天</span>
            </button>
            <button aria-label="设置" title="设置" onClick={onSettingsOpen}>
              <FiSettings />
            </button>
          </div>
          <CompanionEntry />
          <ChatHistoryPanel />
        </Box>
      )}
      {!isCollapsed && settingsOpen && (
        <SettingUI
          open={settingsOpen}
          onClose={onSettingsClose}
          onToggle={onToggle}
        />
      )}
    </Box>
  );
}
export default Sidebar;
