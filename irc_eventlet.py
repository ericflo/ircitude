import eventlet

import datetime

__version__ = '0.0.1'


class RPL(object):
    """
    Reply codes, mostly from http://www.irchelp.org/irchelp/rfc/chapter6.html#c6_2
    """
    WELCOME = '001'
    YOURHOST = '002'
    CREATED = '003'
    MYINFO = '004'
    ENDOFWHO = '315'
    WHOREPLY = '352'
    NAMREPLY = '353'
    ENDOFNAMES = '366'
    MOTDSTART = '375'
    ENDOFMOTD = '376'


class ERR(object):
    """
    Error codes, mostly from http://www.irchelp.org/irchelp/rfc/chapter6.html
    """
    NOSUCHCHANNEL = '403'
    UNKNOWNMODE = '472'
    INVITEONLYCHAN = '473'
    NOTREGISTERED = '451'


class ClientQuitException(Exception):
    pass


class IRCClient(object):
    def __init__(self, server_name, conn, writer, reader, created=None,
        server_motd=None, server_badauth=None):

        self.server_name = server_name
        self.server_motd = server_motd or 'Message of the day'
        self.server_badauth = (server_badauth or
            'Your username and password were not recognized')
        
        self._conn = conn
        self._writer = writer
        self._reader = reader
        self._created = created or datetime.datetime.utcnow()
        
        self.channels = set()
        
        self.password = None
        self.nick = None
    
    def auth(self):
        """
        Called once the nick command has been issued.
        """
        return True
    
    def startup(self):
        """
        This is executed when the server starts up.
        """
        pass
    
    def shutdown(self):
        """
        This is executed when the server shuts down.
        """
        pass
    
    def channel_exists(self, channel):
        # This is for a subclass to implement
        # raise NotImplementedError
        return channel == '#testing123'
    
    def channel_allowed(self, channel):
        # This is for a subclass to implement
        # raise NotImplementedError
        return True
    
    def channel_nicks(self, channel):
        # This is for a subclass to implement
        # raise NotImplementedError
        return [self.nick]
    
    def channel_subscribe(self, channel):
        # This is for a subclass to implement
        # raise NotImplementedError
        pass
    
    def channel_unsubscribe(self, channel):
        # This is for a subclass to implement
        # raise NotImplementedError
        pass
    
    def channel_message(self, channel, message):
        """
        This is useful for a subclass to implement when a new message is
        received from the user.
        """
        pass
    
    def user_message(self, nick, message):
        """
        This is useful for a subclass to implement when a new private message
        is received from the user.
        """
        pass
    
    def _send(self, line):
        print '<<<', repr(line)
        self._writer.write(line + '\r\n')
        self._writer.flush()
    
    def send(self, cmd, text=None):
        self._send(':%s %s %s %s' % (self.server_name, cmd, self.nick, text))
    
    def send_command(self, from_nick, command, channel, msg=None):
        line = ':%s!%s@%s %s %s' % (
            from_nick,
            from_nick,
            self.server_name,
            command,
            channel,
        )
        if msg:
            line += ' :' + msg
        self._send(line)
    
    def handle(self):
        try:
            for line in self._reader:
                # Get rid of the CRLF
                if line.endswith('\r\n'):
                    line = line[:-2]
            
                print '>>>', repr(line)

                if line.startswith(':'):
                    self.handle_message(line)
                else:
                    command, _, rest = line.partition(' ')
                    handler_name = 'handle_%s' % (command,)
                    getattr(self, handler_name, self.handle_UNKNOWN)(line)
        except ClientQuitException:
            pass
        
        for channel in self.channels:
            self.channel_unsubscribe(channel)
        
        self.shutdown()
        
        self._writer.close()
        self._reader.close()
        self._conn.close()
    
    def handle_PRIVMSG(self, line):
        metadata, _, message = line.partition(':')
        _, _, channel = metadata.strip().partition(' ')
        if channel[0] == '#':
            self.channel_message(channel, message)
        else:
            self.user_message(channel, message)
    
    def handle_PASS(self, line):
        try:
            _, password = line.split(' ')
        except ValueError:
            raise ClientQuitException()

        self.password = password
    
    def handle_NICK(self, line):
        split_line = line.split(' ')
        try:
            self.nick = split_line[1]
        except IndexError:
            raise ClientQuitException()

        if not self.auth():
            self.send(ERR.NOTREGISTERED, self.server_badauth)
            raise ClientQuitException()

        self.send(RPL.MOTDSTART, ':%s' % (self.server_motd,))
        self.send(RPL.ENDOFMOTD, ':End of /MOTD command.')
        self.send(RPL.WELCOME, ':Welcome to %s' % (self.server_name,))
        self.send(RPL.YOURHOST, ':Your host is %s, running version %s' % (
            self.server_name,
            __version__,
        ))
        self.send(RPL.CREATED,
            ':This server was created %s' % (self._created,))
        self.send(RPL.MYINFO, '%s :%s w n' % (self.server_name, __version__))
        self.startup()
    
    def handle_USER(self, line):
        pass
    
    def handle_PING(self, line):
        self.send('PONG', self.server_name)
    
    def handle_JOIN(self, line):
        try:
            channels = line.split(' ')[1].split(',')
        except IndexError:
            raise ClientQuitException()

        for channel in channels:
            if channel.startswith('#'):
                pass
            elif channel.startswith('&'):
                channel = '#' + channel[1:]
            else:
                # Channel is malformed if it doesn't start with a # or a &
                # so we just skip it, assuming the client is an idiot.
                continue
            
            if not self.channel_exists(channel):
                self.send(ERR.NOSUCHCHANNEL, '%s :No such channel' % (channel,))
                return
            
            if not self.channel_allowed(channel):
                self.send(ERR.INVITEONLYCHAN,
                    '%s :Cannot join channel (+i)' % (channel,))
                return
            
            self.channels.add(channel)
            self.channel_subscribe(channel)
            self.send_command(self.nick, 'JOIN', channel)
            
            # Send the logged-in nicks, in chunks of 10
            nicks = self.channel_nicks(channel)
            while len(nicks):
                some, nicks = nicks[:10], nicks[10:]
                self.send(RPL.NAMREPLY, '= %s :%s' % (channel, ' '.join(some)))
            self.send(RPL.ENDOFNAMES, '%s :End of /NAMES list' % (channel,))
    
    def handle_WHO(self, line):
        try:
            channel = line.split(' ')[1]
        except IndexError:
            return
        for nick in self.channel_nicks(channel):
            # Really not sure why we have to repeat so many times
            self.send(RPL.WHOREPLY, '%s %s %s %s %s H :0 %s' % (
                channel,
                nick,
                self.server_name,
                self.server_name,
                nick,
                nick,
            ))
        self.send(RPL.ENDOFWHO, '%s :End of /WHO list.' % (channel,))
    
    def handle_MODE(self, line):
        # LOL
        self.send(ERR.UNKNOWNMODE, ':Unknown MODE flag.')
    
    def handle_QUIT(self, line):
        raise ClientQuitException()
    
    def handle_UNKNOWN(self, line):
        print line


def serve(port=6667):
    print 'IRC server starting up on port %s' % (port,)
    now = datetime.datetime.utcnow()
    server = eventlet.listen(('0.0.0.0', port))
    while 1:
        conn, addr = server.accept()
        writer, reader = conn.makefile('w'), conn.makefile('r')
        client = IRCClient('localhost', conn, writer, reader, created=now)
        eventlet.spawn_n(client.handle)

if __name__ == '__main__':
    serve()